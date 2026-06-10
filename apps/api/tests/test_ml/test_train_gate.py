"""Tests for ml/train_gate.py and its wiring into scripts/train_models.py.

The gate's pure functions are tested directly; the train_ensemble wiring is
tested end-to-end on small synthetic data (real sklearn fit, no network).
"""

import sys
from pathlib import Path

_api = Path(__file__).parents[2]
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_api / "scripts"))

import numpy as np
import pandas as pd
import pytest

from ml.train_gate import GateResult, evaluate_train_gate, majority_baseline, rank_ic


# ---------------------------------------------------------------------------
# majority_baseline
# ---------------------------------------------------------------------------

def test_majority_baseline_simple():
    assert majority_baseline([1, 1, 1, 0]) == pytest.approx(0.75)


def test_majority_baseline_empty():
    assert majority_baseline([]) == 0.0


def test_majority_baseline_uniform():
    assert majority_baseline([0, 1, 2]) == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# rank_ic
# ---------------------------------------------------------------------------

def test_rank_ic_perfect_monotone():
    assert rank_ic([1, 2, 3, 4], [0.01, 0.02, 0.03, 0.04]) == pytest.approx(1.0)


def test_rank_ic_inverted():
    assert rank_ic([4, 3, 2, 1], [0.01, 0.02, 0.03, 0.04]) == pytest.approx(-1.0)


def test_rank_ic_constant_scores_is_none():
    assert rank_ic([0.5, 0.5, 0.5, 0.5], [0.01, -0.02, 0.03, 0.0]) is None


def test_rank_ic_constant_returns_is_none():
    assert rank_ic([1, 2, 3, 4], [0.0, 0.0, 0.0, 0.0]) is None


def test_rank_ic_too_few_samples_is_none():
    assert rank_ic([1, 2], [0.1, 0.2]) is None


def test_rank_ic_length_mismatch_is_none():
    assert rank_ic([1, 2, 3], [0.1, 0.2]) is None


# ---------------------------------------------------------------------------
# evaluate_train_gate
# ---------------------------------------------------------------------------

def _passing_inputs():
    # 6 val rows; model gets 5/6 right (maj baseline = 3/6 = 0.5); scores track returns.
    y_val = [2, 2, 0, 0, 1, 1]
    pred = [2, 2, 0, 0, 1, 0]
    scores = [0.9, 0.8, -0.7, -0.6, 0.05, 0.1]
    rets = [0.03, 0.02, -0.03, -0.02, 0.001, 0.002]
    return y_val, pred, scores, rets


def test_gate_passes_on_good_model():
    g = evaluate_train_gate(*_passing_inputs())
    assert isinstance(g, GateResult)
    assert g.passed and g.reasons == []
    assert g.val_accuracy > g.majority_baseline
    assert g.rank_ic is not None and g.rank_ic > 0


def test_gate_fails_when_accuracy_at_baseline():
    y_val = [1, 1, 1, 0, 0, 2]   # majority 'hold' = 0.5
    pred = [1, 1, 1, 1, 1, 1]    # always-majority → acc == baseline → fail
    scores = [0.9, 0.8, -0.7, -0.6, 0.05, 0.1]
    rets = [0.03, 0.02, -0.03, -0.02, 0.001, 0.002]
    g = evaluate_train_gate(y_val, pred, scores, rets)
    assert not g.passed
    assert any("majority-class baseline" in r for r in g.reasons)


def test_gate_fails_on_negative_rank_ic():
    y_val, pred, _, rets = _passing_inputs()
    inverted = [-0.9, -0.8, 0.7, 0.6, -0.05, -0.1]
    g = evaluate_train_gate(y_val, pred, inverted, rets)
    assert not g.passed
    assert any("not positive" in r for r in g.reasons)


def test_gate_fails_on_undefined_rank_ic():
    y_val, pred, _, rets = _passing_inputs()
    g = evaluate_train_gate(y_val, pred, [0.0] * 6, rets)
    assert not g.passed
    assert any("undefined" in r for r in g.reasons)


def test_gate_result_as_dict_round_numbers():
    g = evaluate_train_gate(*_passing_inputs())
    d = g.as_dict()
    assert d["passed"] is True
    assert isinstance(d["val_accuracy"], float)
    assert d["reasons"] == []


# ---------------------------------------------------------------------------
# train_ensemble wiring — refuses to save, --force overrides
# ---------------------------------------------------------------------------

def _synthetic(n=300, signal=True, seed=7):
    """Small feature frame + labels. signal=True embeds a learnable monotone
    pattern; signal=False makes labels/returns pure noise so no model can beat
    the majority baseline or post positive rank-IC."""
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({
        "f1": rng.normal(size=n),
        "f2": rng.normal(size=n),
        "f3": rng.normal(size=n),
    })
    if signal:
        raw = X["f1"].to_numpy() * 0.02 + rng.normal(0, 0.001, n)
    else:
        raw = rng.normal(0, 0.02, n)
    y = np.where(raw > 0.005, 2, np.where(raw < -0.005, 0, 1))
    return X, y, raw


def test_train_ensemble_saves_when_gate_passes(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.model_dir", str(tmp_path))
    import train_models

    X, y, rets = _synthetic(signal=True)
    out = train_models.train_ensemble(
        X, y, rets, asset_class="equity", version="vtest", symbols=["SYN"],
        timeframe="daily", threshold=0.005,
    )
    assert out is not None and Path(out).exists()
    card = Path(out[:-4] + ".card.json")
    assert card.exists()
    import json
    gate = json.loads(card.read_text())["gate"]
    assert gate["passed"] is True


def test_train_ensemble_refuses_on_noise(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.model_dir", str(tmp_path))
    import train_models

    X, y, rets = _synthetic(signal=False)
    out = train_models.train_ensemble(
        X, y, rets, asset_class="equity", version="vtest", symbols=["SYN"],
        timeframe="daily", threshold=0.005,
    )
    assert out is None
    assert not (tmp_path / "equity_ensemble_vtest.pkl").exists()
    # The card is still written — the verdict is the record.
    card = tmp_path / "equity_ensemble_vtest.card.json"
    assert card.exists()
    import json
    parsed = json.loads(card.read_text())
    assert parsed["gate"]["passed"] is False and parsed["gate"]["reasons"]
    assert parsed["artifact"] is None


def test_train_ensemble_force_overrides_gate(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.model_dir", str(tmp_path))
    import train_models

    X, y, rets = _synthetic(signal=False)
    out = train_models.train_ensemble(
        X, y, rets, asset_class="equity", version="vtest", symbols=["SYN"],
        timeframe="daily", threshold=0.005, force=True,
    )
    assert out is not None and Path(out).exists()
    import json
    parsed = json.loads(Path(out[:-4] + ".card.json").read_text())
    assert parsed["gate"]["passed"] is False
    assert parsed["gate_forced"] is True
