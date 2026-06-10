"""Live-trading safety scaffolding tests (PR-N).

Verifies the first-live-order gate blocks real-money orders until approved while
leaving paper untouched, the fail-safe default, and the preflight report. The
internal-only endpoints are covered via the shared client fixture.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import execution.live_guard as lg


def _paper_exec():
    return SimpleNamespace(name="paper")


def _live_exec(name="alpaca"):
    return SimpleNamespace(name=name)


# ---------------------------------------------------------------------------
# is_live_order
# ---------------------------------------------------------------------------

def test_paper_executor_is_never_live():
    assert lg.is_live_order("equity", _paper_exec()) is False


def test_live_venue_with_paper_flag_off_is_live(monkeypatch):
    monkeypatch.setattr("config.settings.alpaca_paper", False)
    assert lg.is_live_order("equity", _live_exec("alpaca")) is True


def test_live_venue_with_paper_flag_on_is_not_live(monkeypatch):
    monkeypatch.setattr("config.settings.alpaca_paper", True)
    assert lg.is_live_order("equity", _live_exec("alpaca")) is False


# ---------------------------------------------------------------------------
# approval round-trip + fail-safe
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_redis(monkeypatch):
    store: dict[str, str] = {}

    class _R:
        async def delete(self, key):
            store.pop(key, None)
            return 1

    async def _set(key, value, ttl):
        store[key] = json.dumps(value)

    async def _get(key):
        v = store.get(key)
        return json.loads(v) if v is not None else None

    monkeypatch.setattr(lg, "get_redis", lambda: _R())
    monkeypatch.setattr(lg, "cache_set", _set)
    monkeypatch.setattr(lg, "cache_get", _get)
    return store


@pytest.mark.asyncio
async def test_approve_then_revoke(fake_redis):
    assert await lg.live_approved() is False
    await lg.approve_live(reason="go-live")
    assert await lg.live_approved() is True
    await lg.revoke_live()
    assert await lg.live_approved() is False


@pytest.mark.asyncio
async def test_live_approved_fail_safe_false_on_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("redis down")
    monkeypatch.setattr(lg, "cache_get", boom)
    # Fail-safe: a cache outage must BLOCK live (return False), not allow it.
    assert await lg.live_approved() is False


# ---------------------------------------------------------------------------
# block_reason gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_block_reason_allows_paper(fake_redis):
    assert await lg.block_reason("equity", _paper_exec()) is None


@pytest.mark.asyncio
async def test_block_reason_blocks_unapproved_live(fake_redis, monkeypatch):
    monkeypatch.setattr("config.settings.alpaca_paper", False)
    reason = await lg.block_reason("equity", _live_exec("alpaca"))
    assert reason is not None and "not approved" in reason


@pytest.mark.asyncio
async def test_block_reason_allows_approved_live(fake_redis, monkeypatch):
    monkeypatch.setattr("config.settings.alpaca_paper", False)
    await lg.approve_live()
    assert await lg.block_reason("equity", _live_exec("alpaca")) is None


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preflight_reports_checks(fake_redis, monkeypatch):
    monkeypatch.setattr("config.settings.per_trade_notional_cap_usd", 200.0)
    report = await lg.preflight()
    names = {c["check"] for c in report["checks"]}
    assert {"order_caps_configured", "kill_switch_available", "live_approved", "venue_modes"} <= names
    assert report["checks"][0]["passed"] is True   # caps configured
    assert "ready" in report and "venue_modes" in report


# ---------------------------------------------------------------------------
# worker gate: a blocked live order never reaches the executor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_blocks_unapproved_live_order(monkeypatch):
    import sys
    from pathlib import Path
    wd = Path(__file__).parents[2] / "worker"
    if str(wd) not in sys.path:
        sys.path.insert(0, str(wd))
    from unittest.mock import AsyncMock, MagicMock

    import tick

    from execution.base import OrderIntent, OrderType, Side, TimeInForce

    # block_reason returns a reason → the order must be skipped before place().
    async def _blocked(asset_class, executor):
        return "live order blocked — not approved"
    monkeypatch.setattr("execution.live_guard.block_reason", _blocked)

    executor = MagicMock()
    executor.place = AsyncMock()
    session = MagicMock()
    session.add = MagicMock()
    intent = OrderIntent(asset_class="equity", symbol="AAPL", side=Side.BUY,
                         order_type=OrderType.MARKET, qty=1.0, limit_px=100.0,
                         time_in_force=TimeInForce.DAY, client_order_id="equity:AAPL:buy:1")

    async def _none(session, coid):
        return None
    monkeypatch.setattr(tick, "already_submitted", _none)

    report, pos, skip_reason = await tick._submit_and_persist(session, executor, intent, None)
    assert report is None                       # skipped
    assert skip_reason == "live_blocked"        # blocked by live guard, not idempotency
    executor.place.assert_not_awaited()         # never reached the broker
