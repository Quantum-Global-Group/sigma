"""Control-flow guards for the worker allocation rebalancer.

The order math is covered in test_ml/test_allocation.py; here we verify the
worker path's gates — disabled, and the once-a-month idempotency — don't touch
the market/executor when they shouldn't.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_api = Path(__file__).parents[1]
_apps = _api.parent
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_apps))

from config import settings
from worker import allocation_tick


def _no_market(monkeypatch):
    """Trip-wire: fail if the rebalancer reaches data/execution."""
    boom = MagicMock(side_effect=AssertionError("should not reach the market"))
    monkeypatch.setattr(allocation_tick, "get_market_adapter", boom)
    monkeypatch.setattr(allocation_tick, "get_executor", boom)


def test_disabled_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "allocation_enabled", False)
    _no_market(monkeypatch)
    asyncio.run(allocation_tick.allocation_rebalance())   # returns without touching anything


def test_no_weights_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "allocation_enabled", True)
    monkeypatch.setattr(settings, "allocation_weights", "")
    _no_market(monkeypatch)
    asyncio.run(allocation_tick.allocation_rebalance())


def test_monthly_guard_skips_when_already_rebalanced(monkeypatch):
    monkeypatch.setattr(settings, "allocation_enabled", True)
    monkeypatch.setattr(settings, "allocation_weights", "SPY:1.0")
    monkeypatch.setattr(settings, "allocation_force", False)
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    monkeypatch.setattr(allocation_tick, "cache_get", AsyncMock(return_value=ym))
    _no_market(monkeypatch)
    asyncio.run(allocation_tick.allocation_rebalance())   # guard short-circuits


def test_force_bypasses_guard_but_market_closed_defers(monkeypatch):
    monkeypatch.setattr(settings, "allocation_enabled", True)
    monkeypatch.setattr(settings, "allocation_weights", "SPY:1.0")
    monkeypatch.setattr(settings, "allocation_force", True)
    monkeypatch.setattr(allocation_tick, "cache_get", AsyncMock(return_value="2000-01"))
    # market closed → defers cleanly without an executor
    adapter = MagicMock()
    adapter.is_market_open = MagicMock(return_value=False)
    monkeypatch.setattr(allocation_tick, "get_market_adapter", MagicMock(return_value=adapter))
    ex = MagicMock(side_effect=AssertionError("no executor when market closed"))
    monkeypatch.setattr(allocation_tick, "get_executor", ex)
    asyncio.run(allocation_tick.allocation_rebalance())
    adapter.is_market_open.assert_called_once()
