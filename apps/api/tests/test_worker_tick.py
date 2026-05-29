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

def _make_ohlcv(n: int = 80) -> pd.DataFrame:
    """Raw OHLCV with the lowercase long names MarketAdapters return.

    _model_pred runs ml.features.build_features on this, so it needs the
    open/high/low/close/volume columns and enough rows (≥~55) for the rolling
    windows to survive dropna()."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 0.5, n),
            "high": close + np.abs(rng.normal(0, 1, n)),
            "low": close - np.abs(rng.normal(0, 1, n)),
            "close": close,
            "volume": rng.uniform(1e6, 5e6, n),
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
    assert _model_pred(None, "AAPL", _make_ohlcv()) == {}


def test_model_pred_empty_when_df_empty():
    fake = MagicMock()
    assert _model_pred(fake, "AAPL", pd.DataFrame()) == {}


def test_model_pred_returns_symbol_dict():
    # build_features runs for real on the OHLCV; the model is mocked, so
    # whatever frame it receives, predict returns the stubbed value.
    fake = MagicMock()
    fake.predict.return_value = MagicMock(predicted_return=0.03)
    result = _model_pred(fake, "AAPL", _make_ohlcv())
    assert list(result.keys()) == ["AAPL"]
    assert result["AAPL"] == pytest.approx(0.03)
    # confirm the model was fed a non-empty build_features frame, not raw OHLCV
    fed = fake.predict.call_args[0][0]
    assert "rsi_14" in fed.columns and not fed.empty


def test_model_pred_swallows_predict_exception():
    fake = MagicMock()
    fake.predict.side_effect = RuntimeError("model exploded")
    result = _model_pred(fake, "TSLA", _make_ohlcv())
    assert result == {}


def test_model_pred_casts_to_float():
    """predicted_return might come back as numpy scalar — must be plain float."""
    fake = MagicMock()
    fake.predict.return_value = MagicMock(predicted_return=np.float32(0.05))
    result = _model_pred(fake, "MSFT", _make_ohlcv())
    assert isinstance(result["MSFT"], float)
