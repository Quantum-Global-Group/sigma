"""Tests for the options worker (Phase 6) — no live OpenD, no real DB.

Strategy: inject fake objects at every boundary so the gate logic and
persistence paths are exercised without network or database dependencies.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

# Make apps/worker importable from the apps/api test runner (mirrors test_worker_tick.py).
_worker_dir = Path(__file__).parents[2] / "worker"
if str(_worker_dir) not in sys.path:
    sys.path.insert(0, str(_worker_dir))

# ---------------------------------------------------------------------------
# Fake moomoo SDK (same pattern as test_moomoo_connector.py)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_moomoo(monkeypatch):
    m = types.ModuleType("moomoo")
    m.RET_OK = 0
    for cls in ("TrdEnv", "TrdSide", "OrderType", "KLType", "TrdMarket", "SecurityFirm"):
        setattr(m, cls, type(cls, (), {attr: attr for attr in ("BUY", "SELL", "MARKET", "NORMAL",
                                                                  "K_DAY", "K_5M", "US", "FUTUINC",
                                                                  "SIMULATE", "REAL")}))
    m.OpenQuoteContext = object
    m.OpenSecTradeContext = object
    monkeypatch.setitem(sys.modules, "moomoo", m)
    # These tests exercise tick/gate logic, not the OpenD gateway probe — disable
    # supervision so options_tick_once doesn't bail on an unreachable gateway.
    monkeypatch.setattr("config.settings.opend_check_enabled", False)
    return m


# ---------------------------------------------------------------------------
# Helpers — minimal synthetic chain
# ---------------------------------------------------------------------------

def _make_chain(spot: float = 150.0, right: str = "call") -> list:
    from markets.options import OptionContract, OptionQuote
    c = OptionContract("AAPL", date(2026, 3, 20), spot, right, f"US.AAPL260320{'C' if right == 'call' else 'P'}00150000")
    return [OptionQuote(
        contract=c, bid=5.00, ask=5.20, last=5.10,
        volume=1000, open_interest=5000,
        implied_vol=0.30, delta=0.50, gamma=0.03, theta=-0.05, vega=0.15,
        ts=datetime.now(timezone.utc),
    )]


def _make_both_chain(spot: float = 150.0) -> list:
    return _make_chain(spot, "call") + _make_chain(spot, "put")


def _make_ohlcv(n: int = 60) -> pd.DataFrame:
    """Synthetic daily OHLCV with a gentle uptrend."""
    import numpy as np
    rng = np.random.default_rng(42)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, n)))
    return pd.DataFrame({
        "open": closes * 0.999,
        "high": closes * 1.005,
        "low": closes * 0.995,
        "close": closes,
        "volume": rng.uniform(1e6, 2e6, n),
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))


# ---------------------------------------------------------------------------
# Unit tests for gate helpers (pure, no I/O)
# ---------------------------------------------------------------------------

def test_gate_data_accepts_valid_chain():
    from options_tick import _gate_data
    chain = _make_both_chain()
    ok, reasons = _gate_data(chain, 150.0)
    assert ok, reasons


def test_gate_data_rejects_zero_spot():
    from options_tick import _gate_data
    ok, reasons = _gate_data(_make_both_chain(), 0.0)
    assert not ok
    assert any("spot" in r for r in reasons)


def test_gate_data_rejects_empty_chain():
    from options_tick import _gate_data
    ok, reasons = _gate_data([], 150.0)
    assert not ok
    assert any("empty" in r for r in reasons)


def test_gate_data_rejects_one_sided_book():
    from options_tick import _gate_data
    from markets.options import OptionContract, OptionQuote
    c = OptionContract("AAPL", date(2026, 3, 20), 150.0, "call", "x")
    chain = [OptionQuote(c, bid=0.0, ask=0.0, last=5.0, volume=100, open_interest=500)]
    ok, reasons = _gate_data(chain, 150.0)
    assert not ok


def test_gate_signal_rejects_low_confidence(monkeypatch):
    monkeypatch.setattr("config.settings.min_signal_confidence", 0.5)
    from options_tick import _gate_signal
    from ml.regime import Regime
    ok, reasons = _gate_signal(0.1, Regime.TRENDING_UP, 0.7)
    assert not ok
    assert any("confidence" in r for r in reasons)


def test_gate_signal_rejects_unknown_regime(monkeypatch):
    monkeypatch.setattr("config.settings.min_signal_confidence", 0.1)
    from options_tick import _gate_signal
    from ml.regime import Regime
    ok, reasons = _gate_signal(0.8, Regime.UNKNOWN, 0.7)
    assert not ok
    assert any("unknown" in r.lower() for r in reasons)


def test_gate_signal_rejects_zero_score(monkeypatch):
    monkeypatch.setattr("config.settings.min_signal_confidence", 0.1)
    from options_tick import _gate_signal
    from ml.regime import Regime
    ok, reasons = _gate_signal(0.8, Regime.RANGE, 0.0)
    assert not ok


def test_gate_signal_passes(monkeypatch):
    monkeypatch.setattr("config.settings.min_signal_confidence", 0.1)
    from options_tick import _gate_signal
    from ml.regime import Regime
    ok, reasons = _gate_signal(0.8, Regime.TRENDING_UP, 0.5)
    assert ok, reasons


def test_gate_simulation_rejects_zero_max_loss():
    from options_tick import _gate_simulation
    from options.strategies import OptionStructure
    struct = OptionStructure("long_call", [], 5.0, max_loss=0.0, max_profit=float("inf"),
                              breakevens=[], net_greeks={})
    cand = MagicMock()
    cand.structure = struct
    ok, reasons = _gate_simulation(cand)
    assert not ok
    assert any("max_loss" in r for r in reasons)


def test_gate_simulation_accepts_valid_structure():
    from options_tick import _gate_simulation
    from options.strategies import OptionStructure, StrategyLeg
    chain = _make_both_chain()
    leg = StrategyLeg(chain[0], "long", 1)
    struct = OptionStructure("long_call", [leg], 5.1, max_loss=510.0, max_profit=float("inf"),
                              breakevens=[155.1], net_greeks={"delta": 0.5, "gamma": 0.03,
                                                               "theta": -0.05, "vega": 0.15})
    cand = MagicMock()
    cand.structure = struct
    ok, reasons = _gate_simulation(cand)
    assert ok, reasons


# ---------------------------------------------------------------------------
# _nearest_expiry
# ---------------------------------------------------------------------------

def test_nearest_expiry_picks_closest_in_window():
    from options_tick import _nearest_expiry
    from datetime import date, timedelta
    today = date.today()
    e1 = today + timedelta(days=10)   # too soon (<14)
    e2 = today + timedelta(days=20)   # in window
    e3 = today + timedelta(days=45)   # in window, farther
    e4 = today + timedelta(days=90)   # too far (>60)
    result = _nearest_expiry([e1, e2, e3, e4])
    assert result == e2


def test_nearest_expiry_returns_none_when_none_qualify():
    from options_tick import _nearest_expiry
    from datetime import date, timedelta
    today = date.today()
    result = _nearest_expiry([today + timedelta(days=5), today + timedelta(days=90)])
    assert result is None


# ---------------------------------------------------------------------------
# Full options_tick_once integration smoke test (all mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_options_tick_once_skips_when_market_closed(monkeypatch):
    """If is_market_open() returns False, tick returns without any DB writes."""
    mock_adapter = MagicMock()
    mock_adapter.is_market_open.return_value = False

    with patch("options_tick.get_market_adapter", return_value=mock_adapter), \
         patch("options_tick.get_universe_selector"), \
         patch("options_tick.get_executor"), \
         patch("options_tick.AsyncSessionLocal"):
        from options_tick import options_tick_once
        await options_tick_once()
    mock_adapter.is_market_open.assert_called_once()


@pytest.mark.asyncio
async def test_options_tick_once_gate1_fails_on_empty_chain(monkeypatch):
    """G1 fails when chain query returns empty; no order persisted."""
    import asyncio
    df = _make_ohlcv(60)

    mock_adapter = MagicMock()
    mock_adapter.is_market_open.return_value = True
    mock_adapter.fetch_ohlcv.return_value = df

    mock_option_data = MagicMock()
    mock_option_data.list_expiries.return_value = [
        date.today().__class__.today() + __import__("datetime").timedelta(days=30)
    ]
    mock_option_data.get_chain.return_value = []  # empty chain → G1 fail

    mock_selector = MagicMock()
    mock_selector.select.return_value = ["AAPL"]

    mock_executor = MagicMock()
    mock_executor.get_account_equity = AsyncMock(return_value=50000.0)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    with patch("options_tick.get_market_adapter", return_value=mock_adapter), \
         patch("options_tick.get_universe_selector", return_value=mock_selector), \
         patch("options_tick.get_executor", return_value=mock_executor), \
         patch("options_tick.get_option_data_provider", return_value=mock_option_data), \
         patch("options_tick.AsyncSessionLocal", return_value=mock_session):
        from options_tick import options_tick_once
        await options_tick_once()

    # session.add was not called since we bailed at G1
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_options_tick_once_gate2_fails_on_low_confidence(monkeypatch):
    """G2 fails when signal confidence is too low; no order placed."""
    import datetime
    df = _make_ohlcv(60)
    chain = _make_both_chain(150.0)

    mock_adapter = MagicMock()
    mock_adapter.is_market_open.return_value = True
    mock_adapter.fetch_ohlcv.return_value = df

    mock_option_data = MagicMock()
    mock_option_data.list_expiries.return_value = [date.today() + datetime.timedelta(days=30)]
    mock_option_data.get_chain.return_value = [q.contract for q in chain]
    mock_option_data.get_quotes.return_value = chain

    mock_selector = MagicMock()
    mock_selector.select.return_value = ["AAPL"]

    mock_executor = MagicMock()
    mock_executor.get_account_equity = AsyncMock(return_value=50000.0)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    # Return a result with confidence well below threshold
    fake_combined = MagicMock()
    fake_combined.strength = 0.0
    fake_result = MagicMock()
    fake_result.signal = "HOLD"
    fake_result.confidence = 0.01
    fake_result.model_version = "test"

    monkeypatch.setattr("config.settings.min_signal_confidence", 0.5)

    with patch("options_tick.get_market_adapter", return_value=mock_adapter), \
         patch("options_tick.get_universe_selector", return_value=mock_selector), \
         patch("options_tick.get_executor", return_value=mock_executor), \
         patch("options_tick.get_option_data_provider", return_value=mock_option_data), \
         patch("options_tick.AsyncSessionLocal", return_value=mock_session), \
         patch("options_tick.build_default_combiner") as mock_combiner_fn, \
         patch("options_tick.combine_to_result", return_value=fake_result):
        mock_combiner = MagicMock()
        mock_combiner.combine_signals.return_value = fake_combined
        mock_combiner_fn.return_value = mock_combiner
        from options_tick import options_tick_once
        await options_tick_once()

    mock_session.add.assert_not_called()
    mock_executor.place.assert_not_called()
