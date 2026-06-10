"""Multi-leg settlement tests (PR-M) — per-leg signed Greeks + group-coordinated
close (all legs of a structure exit together)."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from markets.options import OptionContract, OptionQuote
from options.strategies import StrategyLeg

_worker = Path(__file__).parents[2] / "worker"
if str(_worker) not in sys.path:
    sys.path.insert(0, str(_worker))

import options_tick  # noqa: E402
from options_tick import _manage_open_positions, _signed_leg_greeks  # noqa: E402


def _leg(side: str, right: str = "call", strike: float = 100.0):
    c = OptionContract("AAPL", date(2026, 3, 20), strike, right, f"US.AAPL.{right}.{strike}")
    q = OptionQuote(contract=c, bid=3.0, ask=3.2, last=3.1, volume=500, open_interest=1000,
                    implied_vol=0.3, delta=0.5, gamma=0.03, theta=-0.05, vega=0.12)
    return StrategyLeg(q, side, 1)


# ---------------------------------------------------------------------------
# _signed_leg_greeks
# ---------------------------------------------------------------------------

def test_signed_leg_greeks_long_positive():
    g = _signed_leg_greeks(_leg("long"), spot=100.0, T=0.1)
    assert g["delta"] > 0 and g["vega"] > 0


def test_signed_leg_greeks_short_negative():
    g = _signed_leg_greeks(_leg("short"), spot=100.0, T=0.1)
    assert g["delta"] < 0 and g["vega"] < 0     # short flips the sign


def test_signed_leg_greeks_bs_fallback_when_quote_missing():
    c = OptionContract("AAPL", date(2026, 3, 20), 100.0, "call", "x")
    q = OptionQuote(contract=c, bid=3.0, ask=3.2, last=3.1, volume=500, open_interest=1000,
                    implied_vol=0.3, delta=None, gamma=None, theta=None, vega=None)
    g = _signed_leg_greeks(StrategyLeg(q, "long", 1), spot=100.0, T=0.1)
    assert 0.0 < g["delta"] < 1.0               # BS-derived call delta


# ---------------------------------------------------------------------------
# group-coordinated close
# ---------------------------------------------------------------------------

def _pos(structure_id, leg_side, expiry, strike, right="call"):
    recent = datetime.now(timezone.utc) - timedelta(days=2)   # avoid the time-stop
    return SimpleNamespace(
        asset_class="option", symbol=f"AAPL{strike}{right[0].upper()}",
        underlying="AAPL", expiry=expiry, strike=strike, right=right,
        entry_px=3.0, qty=1.0, multiplier=100, entry_ts=recent,
        current_px=None, realized_pnl=0.0, unrealized_pnl=None, closed=False, closed_at=None,
        meta={"structure_id": structure_id, "leg_side": leg_side},
    )


def _ohlcv(n=45):
    import numpy as np
    import pandas as pd
    c = np.linspace(100, 110, n)
    return pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c,
                         "volume": np.full(n, 1e6)})


class _Adapter:
    def fetch_ohlcv(self, symbol, timeframe="daily"):
        return _ohlcv()


def _session_with(positions):
    res = MagicMock()
    res.scalars.return_value = MagicMock(all=lambda: positions)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=res)
    session.add = MagicMock()
    return session


@pytest.fixture
def no_premium_exits(monkeypatch):
    """Isolate multi-leg group logic from PR-I's premium exits (on by default)."""
    monkeypatch.setattr("config.settings.option_stop_loss_pct", 0.0)
    monkeypatch.setattr("config.settings.option_take_profit_pct", 0.0)
    monkeypatch.setattr("config.settings.option_trailing_pct", 0.0)


@pytest.mark.asyncio
async def test_structure_closes_all_legs_together(no_premium_exits):
    """A 2-leg vertical where leg 0 has expired → BOTH legs close this tick."""
    today = date.today()
    long_leg = _pos("S1", "long", today, 100.0)       # expired → settles → triggers group close
    short_leg = _pos("S1", "short", today + timedelta(days=40), 105.0)  # not expired on its own
    session = _session_with([long_leg, short_leg])

    await _manage_open_positions(session, _Adapter())

    assert long_leg.closed is True
    assert short_leg.closed is True                   # force-closed to exit together
    # A settlement Order was written per leg.
    assert session.add.call_count >= 2


@pytest.mark.asyncio
async def test_other_structure_unaffected(no_premium_exits):
    """A second, healthy structure (no expiry/exit) stays open."""
    today = date.today()
    s1 = _pos("S1", "long", today, 100.0)                      # expires → S1 closes
    s2 = _pos("S2", "long", today + timedelta(days=40), 100.0)  # healthy → stays open
    session = _session_with([s1, s2])

    await _manage_open_positions(session, _Adapter())

    assert s1.closed is True
    assert s2.closed is False
    assert s2.unrealized_pnl is not None              # marked, not closed
