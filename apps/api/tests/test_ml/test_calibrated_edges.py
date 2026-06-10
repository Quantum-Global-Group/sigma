"""Tests for calibrated ensemble confidence + measured expected-move edges.

Covers ml/models/ensemble.py (fit_calibration / fit_expected_move / artifact
round-trip / legacy-artifact fallback), combiner.combine_to_result's
expected_move scaling, and worker.tick._expected_move.
"""

import sys
from pathlib import Path

_api = Path(__file__).parents[2]
_worker = _api.parent / "worker"
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_worker))

import joblib
import numpy as np
import pandas as pd
import pytest

from ml.models.ensemble import EnsembleSignalModel
from ml.strategies.base import Signal
from ml.strategies.combiner import combine_to_result


def _fit_model(n=240, seed=3):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({
        "f1": rng.normal(size=n),
        "f2": rng.normal(size=n),
    })
    raw = X["f1"].to_numpy() * 0.02 + rng.normal(0, 0.004, n)
    y = np.where(raw > 0.005, 2, np.where(raw < -0.005, 0, 1))
    model = EnsembleSignalModel(n_estimators=20)
    model.train(X, y)
    return model, X, y, raw


# ---------------------------------------------------------------------------
# fit_calibration
# ---------------------------------------------------------------------------

def test_fit_calibration_sets_calibrator():
    model, X, y, _ = _fit_model()
    assert model.fit_calibration(X.iloc[-60:], y[-60:]) is True
    assert model.calibrator is not None


def test_fit_calibration_skips_tiny_fold():
    model, X, y, _ = _fit_model()
    assert model.fit_calibration(X.iloc[-5:], y[-5:]) is False
    assert model.calibrator is None


def test_calibrated_confidence_is_bounded_and_used():
    model, X, y, _ = _fit_model()
    res_raw = model.predict(X)
    model.fit_calibration(X.iloc[-60:], y[-60:])
    res_cal = model.predict(X)
    assert 0.0 <= res_cal.confidence <= 1.0
    # Same argmax class — calibration is monotonic on confidence only.
    assert res_cal.signal == res_raw.signal


# ---------------------------------------------------------------------------
# fit_expected_move + predicted_return scaling
# ---------------------------------------------------------------------------

def test_fit_expected_move_uses_actionable_rows():
    model, _, _, _ = _fit_model()
    rets = np.array([0.01, -0.02, 0.0005, 0.03])
    y = np.array([2, 0, 1, 2])  # HOLD row excluded
    model.fit_expected_move(rets, y)
    assert model.expected_move == pytest.approx(np.mean([0.01, 0.02, 0.03]))


def test_fit_expected_move_falls_back_to_all_rows_when_all_hold():
    model, _, _, _ = _fit_model()
    model.fit_expected_move(np.array([0.001, -0.002]), np.array([1, 1]))
    assert model.expected_move == pytest.approx(0.0015)


def test_predicted_return_scales_with_expected_move():
    model, X, y, _ = _fit_model()
    model.expected_move = 0.05
    base = model.predict(X).predicted_return
    model.expected_move = 0.01
    scaled = model.predict(X).predicted_return
    if base != 0.0:
        assert scaled == pytest.approx(base * (0.01 / 0.05), rel=1e-3)


# ---------------------------------------------------------------------------
# artifact round-trip + legacy fallback
# ---------------------------------------------------------------------------

def test_artifact_round_trip_preserves_calibration(tmp_path):
    model, X, y, rets = _fit_model()
    model.fit_calibration(X.iloc[-60:], y[-60:])
    model.fit_expected_move(rets, y)
    p = str(tmp_path / "equity_ensemble_vtest.pkl")
    model.save(p)

    loaded = EnsembleSignalModel.load(p)
    assert loaded.calibrator is not None
    assert loaded.expected_move == pytest.approx(model.expected_move)
    a, b = model.predict(X), loaded.predict(X)
    assert a.signal == b.signal
    assert a.confidence == pytest.approx(b.confidence)
    assert a.predicted_return == pytest.approx(b.predicted_return)


def test_legacy_artifact_without_calibration_loads(tmp_path):
    """Artifacts saved before calibration existed lack the new keys — load()
    must fall back to raw confidence and the legacy 5% scale."""
    model, X, _, _ = _fit_model()
    p = str(tmp_path / "legacy.pkl")
    joblib.dump({
        "rf": model.rf,
        "xgb": model.xgb,
        "feature_names": model.feature_names,
        "model_version": "ensemble_v1.0",
    }, p)

    loaded = EnsembleSignalModel.load(p)
    assert loaded.calibrator is None and loaded.expected_move is None
    res = loaded.predict(X)
    assert res.signal in ("BUY", "SELL", "HOLD")


# ---------------------------------------------------------------------------
# combine_to_result expected_move scaling
# ---------------------------------------------------------------------------

def _sig(strength=0.6):
    return Signal(strength=strength, confidence=0.8, method="combined", metadata={})


def test_combine_to_result_uses_expected_move():
    res = combine_to_result(_sig(0.6), expected_move=0.02)
    assert res.predicted_return == pytest.approx(0.6 * 0.02)


def test_combine_to_result_defaults_to_legacy_scale():
    res = combine_to_result(_sig(0.6))
    assert res.predicted_return == pytest.approx(0.6 * 0.05)


def test_combine_to_result_ignores_nonpositive_move():
    assert combine_to_result(_sig(0.6), expected_move=0.0).predicted_return == pytest.approx(0.03)
    assert combine_to_result(_sig(0.6), expected_move=-1.0).predicted_return == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# worker.tick._expected_move
# ---------------------------------------------------------------------------

def test_tick_expected_move_from_atr():
    from tick import _expected_move
    feats = pd.DataFrame({"atr": [1.0, 2.0], "c": [99.0, 100.0]})
    assert _expected_move(feats, 100.0) == pytest.approx(0.02)


def test_tick_expected_move_none_without_atr():
    from tick import _expected_move
    feats = pd.DataFrame({"c": [100.0]})
    assert _expected_move(feats, 100.0) is None


def test_tick_expected_move_none_on_zero_price():
    from tick import _expected_move
    feats = pd.DataFrame({"atr": [1.0], "c": [100.0]})
    assert _expected_move(feats, 0.0) is None
