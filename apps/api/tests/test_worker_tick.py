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

import asyncio
import pandas as pd
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock

from tick import _model_pred, _resolve_model, _resolve_equity, _place_with_retry, _is_transient
from execution.base import ExecutionReport, Order, OrderIntent, OrderStatus, OrderType, Side, TimeInForce


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


# ---------------------------------------------------------------------------
# _resolve_equity (A8)
# ---------------------------------------------------------------------------

def test_resolve_equity_prefers_explicit_arg():
    ex = MagicMock()
    ex.get_account_equity = AsyncMock(return_value=50_000.0)
    assert asyncio.run(_resolve_equity(ex, 1234.0)) == 1234.0
    ex.get_account_equity.assert_not_called()


def test_resolve_equity_uses_live_balance():
    ex = MagicMock()
    ex.get_account_equity = AsyncMock(return_value=42_000.0)
    assert asyncio.run(_resolve_equity(ex, None)) == 42_000.0


def test_resolve_equity_falls_back_to_default(monkeypatch):
    monkeypatch.setattr("config.settings.default_equity", 7777.0)
    ex = MagicMock()
    ex.get_account_equity = AsyncMock(return_value=None)
    assert asyncio.run(_resolve_equity(ex, None)) == 7777.0


def test_resolve_equity_default_on_error(monkeypatch):
    monkeypatch.setattr("config.settings.default_equity", 9000.0)
    ex = MagicMock()
    ex.get_account_equity = AsyncMock(side_effect=RuntimeError("api down"))
    assert asyncio.run(_resolve_equity(ex, None)) == 9000.0


# ---------------------------------------------------------------------------
# _place_with_retry + _is_transient (P1b)
# ---------------------------------------------------------------------------

def _intent() -> OrderIntent:
    return OrderIntent(
        asset_class="equity", symbol="AAPL", side=Side.BUY,
        order_type=OrderType.MARKET, qty=1, limit_px=100.0,
        time_in_force=TimeInForce.DAY, client_order_id="equity:AAPL:buy:1",
    )


def _report(status: OrderStatus, reason=None) -> ExecutionReport:
    order = Order(order_id="x", intent=_intent(), status=status, rejected_reason=reason)
    return ExecutionReport(order=order, fills=[])


def test_is_transient_classification():
    assert _is_transient("Connection timed out")
    assert _is_transient("HTTP 503 Service Unavailable")
    assert _is_transient("rate limit exceeded")
    assert not _is_transient("insufficient buying power")
    assert not _is_transient(None)


def test_place_with_retry_returns_on_success(monkeypatch):
    monkeypatch.setattr("config.settings.executor_max_retries", 2)
    monkeypatch.setattr("config.settings.executor_retry_base_delay", 0.0)
    ex = MagicMock()
    ex.place = AsyncMock(return_value=_report(OrderStatus.FILLED))
    report = asyncio.run(_place_with_retry(ex, _intent()))
    assert report.order.status == OrderStatus.FILLED
    assert ex.place.await_count == 1


def test_place_with_retry_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr("config.settings.executor_max_retries", 2)
    monkeypatch.setattr("config.settings.executor_retry_base_delay", 0.0)
    ex = MagicMock()
    ex.place = AsyncMock(side_effect=[
        _report(OrderStatus.REJECTED, "connection reset"),
        _report(OrderStatus.FILLED),
    ])
    report = asyncio.run(_place_with_retry(ex, _intent()))
    assert report.order.status == OrderStatus.FILLED
    assert ex.place.await_count == 2


def test_place_with_retry_no_retry_on_hard_reject(monkeypatch):
    monkeypatch.setattr("config.settings.executor_max_retries", 3)
    monkeypatch.setattr("config.settings.executor_retry_base_delay", 0.0)
    ex = MagicMock()
    ex.place = AsyncMock(return_value=_report(OrderStatus.REJECTED, "insufficient buying power"))
    report = asyncio.run(_place_with_retry(ex, _intent()))
    assert report.order.status == OrderStatus.REJECTED
    assert ex.place.await_count == 1  # hard reject → no retry


def test_place_with_retry_retries_on_raise_then_reraises(monkeypatch):
    monkeypatch.setattr("config.settings.executor_max_retries", 2)
    monkeypatch.setattr("config.settings.executor_retry_base_delay", 0.0)
    ex = MagicMock()
    ex.place = AsyncMock(side_effect=ConnectionError("boom"))
    with pytest.raises(ConnectionError):
        asyncio.run(_place_with_retry(ex, _intent()))
    assert ex.place.await_count == 3  # initial + 2 retries
