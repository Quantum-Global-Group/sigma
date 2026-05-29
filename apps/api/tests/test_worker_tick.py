"""Tests for the model-wiring helpers in apps/worker/tick.py (A2/A4).

Imports _resolve_model and _model_pred from tick.py directly so we can
unit-test them without spinning up a full async trading cycle.
"""

import sys
from pathlib import Path

# apps/api needs to be on sys.path (config, ml.*); apps/worker for tick.py
_api = Path(__file__).parents[1]
_worker = _api.parent / "worker"
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_worker))

import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock

from tick import _model_pred, _resolve_model


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_feats(n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "o": rng.uniform(100, 110, n),
            "h": rng.uniform(110, 120, n),
            "l": rng.uniform(90, 100, n),
            "c": rng.uniform(100, 110, n),
            "v": rng.uniform(1e5, 1e6, n),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_returns_none_when_no_artifact(tmp_path, monkeypatch):
    """No pkl in model_dir → returns None without raising."""
    monkeypatch.setattr("config.settings.model_dir", str(tmp_path))
    # Clear cache so the fresh tmp_path is used
    import ml.models.registry as reg
    reg.clear_cache()
    result = _resolve_model("equity")
    assert result is None


def test_resolve_model_swallows_import_error(monkeypatch):
    """If the registry import itself fails, _resolve_model returns None."""
    import builtins
    real_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "ml.models.registry":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    result = _resolve_model("equity")
    assert result is None


# ---------------------------------------------------------------------------
# _model_pred
# ---------------------------------------------------------------------------

def test_model_pred_empty_when_no_model():
    assert _model_pred(None, "AAPL", _make_feats()) == {}


def test_model_pred_empty_when_feats_empty():
    fake = MagicMock()
    assert _model_pred(fake, "AAPL", pd.DataFrame()) == {}


def test_model_pred_returns_symbol_dict():
    fake = MagicMock()
    fake.predict.return_value = MagicMock(predicted_return=0.03)
    result = _model_pred(fake, "AAPL", _make_feats())
    assert list(result.keys()) == ["AAPL"]
    assert result["AAPL"] == pytest.approx(0.03)


def test_model_pred_swallows_predict_exception():
    fake = MagicMock()
    fake.predict.side_effect = RuntimeError("model exploded")
    result = _model_pred(fake, "TSLA", _make_feats())
    assert result == {}


def test_model_pred_casts_to_float():
    """predicted_return might come back as numpy scalar — must be plain float."""
    fake = MagicMock()
    fake.predict.return_value = MagicMock(predicted_return=np.float32(0.05))
    result = _model_pred(fake, "MSFT", _make_feats())
    assert isinstance(result["MSFT"], float)
