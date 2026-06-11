"""Tests for partial-fill reconciliation (apps/worker/fill_reconcile.py) and
the Alpaca broker-truth hooks (get_broker_positions / get_order_status)."""

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mirror the runtime layout: apps/api on path (config/db/execution import flat)
# and apps/ on path so `worker` resolves as a package, exactly as main.py runs it.
_api = Path(__file__).parents[1]
_apps = _api.parent
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_apps))

from execution.base import BrokerOrderView
from worker.fill_reconcile import (
    FillReconcileSummary,
    compute_fill_delta,
    is_terminal,
    reconcile_fills,
)

HOUSE = uuid.UUID("00000000-0000-0000-0000-000000000002")


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------

def test_terminal_statuses():
    assert is_terminal("filled")
    assert is_terminal("OrderStatus.CANCELED")
    assert is_terminal("expired")
    assert not is_terminal("partially_filled")
    assert not is_terminal("submitted")
    assert not is_terminal("")


# ---------------------------------------------------------------------------
# compute_fill_delta — pure tranche math
# ---------------------------------------------------------------------------

def test_no_delta_when_broker_matches():
    assert compute_fill_delta(5.0, 100.0, BrokerOrderView(5.0, 100.0, "filled")) is None


def test_late_full_fill_from_zero():
    dqty, dpx = compute_fill_delta(0.0, 0.0, BrokerOrderView(5.0, 101.0, "filled"))
    assert dqty == pytest.approx(5.0)
    assert dpx == pytest.approx(101.0)


def test_partial_to_full_tranche_price_converges_avg():
    # DB recorded 2 @ 100; broker now 5 @ 102 cumulative.
    # Tranche: 3 @ (5*102 - 2*100)/3 = 310/3.
    dqty, dpx = compute_fill_delta(2.0, 100.0, BrokerOrderView(5.0, 102.0, "filled"))
    assert dqty == pytest.approx(3.0)
    assert dpx == pytest.approx(310.0 / 3.0)
    # Applying the tranche reproduces the broker's cumulative average exactly.
    assert (2.0 * 100.0 + dqty * dpx) / 5.0 == pytest.approx(102.0)


def test_degenerate_implied_price_falls_back_to_avg():
    # Implied price would be negative (weird broker data) → use cumulative avg.
    dqty, dpx = compute_fill_delta(2.0, 200.0, BrokerOrderView(2.5, 100.0, "filled"))
    assert dqty == pytest.approx(0.5)
    assert dpx == pytest.approx(100.0)


def test_no_avg_price_falls_back_to_db_price():
    dqty, dpx = compute_fill_delta(2.0, 100.0, BrokerOrderView(3.0, None, "partially_filled"))
    assert dqty == pytest.approx(1.0)
    assert dpx == pytest.approx(100.0)


def test_no_usable_price_returns_none():
    assert compute_fill_delta(0.0, 0.0, BrokerOrderView(3.0, None, "filled")) is None


def test_broker_less_than_db_returns_none():
    assert compute_fill_delta(5.0, 100.0, BrokerOrderView(3.0, 100.0, "filled")) is None


# ---------------------------------------------------------------------------
# reconcile_fills — IO wrapper
# ---------------------------------------------------------------------------

def _order_row(symbol="AAPL", qty=0.0, px=0.0, side="buy", status="submitted",
               external_id="brk-1", executor="alpaca"):
    row = MagicMock()
    row.symbol = symbol
    row.qty = qty
    row.px = px
    row.side = side
    row.status = status
    row.external_id = external_id
    row.executor = executor
    row.ts = datetime.now(timezone.utc)
    return row


def _session(orders, position=None):
    """Mock session: first execute() returns orders, later ones return the position."""
    order_res = MagicMock()
    order_res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=orders)))
    pos_res = MagicMock()
    pos_res.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=position)))
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[order_res] + [pos_res] * 8)
    session.add = MagicMock()
    return session


def _patch_tick_helpers(monkeypatch, affected=None):
    """Stub tick's position math — reconcile_fills imports it lazily at call
    time, so patching the worker.tick module attributes is sufficient."""
    apply_mock = AsyncMock(return_value=affected)
    ensure_mock = AsyncMock()
    import worker.tick as tick_mod
    monkeypatch.setattr(tick_mod, "_apply_fill_to_position", apply_mock)
    monkeypatch.setattr(tick_mod, "_ensure_exit_state", ensure_mock)
    return apply_mock, ensure_mock


def test_skips_when_executor_lacks_hook():
    executor = MagicMock(spec=["name", "place"])
    session = _session([])
    s = asyncio.run(reconcile_fills(session, asset_class="equity", executor=executor, account_id=HOUSE))
    assert s.supported is False
    session.execute.assert_not_called()


def test_late_fill_applies_delta_and_seeds_exit_state(monkeypatch):
    affected = MagicMock(closed=False, id=uuid.uuid4())
    apply_mock, ensure_mock = _patch_tick_helpers(monkeypatch, affected=affected)

    row = _order_row(qty=0.0, px=0.0, status="submitted")
    executor = MagicMock()
    executor.name = "alpaca"
    executor.get_order_status = AsyncMock(return_value=BrokerOrderView(5.0, 101.0, "filled"))

    session = _session([row], position=None)
    s = asyncio.run(reconcile_fills(session, asset_class="equity", executor=executor, account_id=HOUSE))

    assert s.deltas_applied == 1 and s.status_synced == 1
    kw = apply_mock.await_args.kwargs
    assert kw["qty"] == pytest.approx(5.0) and kw["price"] == pytest.approx(101.0)
    ensure_mock.assert_awaited_once()
    assert row.qty == 5.0 and row.px == 101.0 and row.status == "filled"


def test_status_only_sync_for_canceled_unfilled(monkeypatch):
    apply_mock, _ = _patch_tick_helpers(monkeypatch)
    row = _order_row(qty=0.0, px=0.0, status="submitted")
    executor = MagicMock()
    executor.name = "alpaca"
    executor.get_order_status = AsyncMock(return_value=BrokerOrderView(0.0, None, "canceled"))

    session = _session([row])
    s = asyncio.run(reconcile_fills(session, asset_class="equity", executor=executor, account_id=HOUSE))
    assert s.deltas_applied == 0 and s.status_synced == 1
    apply_mock.assert_not_awaited()
    assert row.status == "canceled"


def test_late_sell_without_position_is_divergence(monkeypatch):
    apply_mock, _ = _patch_tick_helpers(monkeypatch)
    row = _order_row(qty=0.0, px=100.0, side="sell", status="submitted")
    executor = MagicMock()
    executor.name = "alpaca"
    executor.get_order_status = AsyncMock(return_value=BrokerOrderView(2.0, 99.0, "filled"))

    session = _session([row], position=None)
    s = asyncio.run(reconcile_fills(session, asset_class="equity", executor=executor, account_id=HOUSE))
    assert s.deltas_applied == 0
    assert len(s.divergences) == 1 and "no open position" in s.divergences[0]
    apply_mock.assert_not_awaited()


def test_broker_under_db_is_divergence_not_shrunk(monkeypatch):
    apply_mock, _ = _patch_tick_helpers(monkeypatch)
    row = _order_row(qty=5.0, px=100.0, status="partially_filled")
    executor = MagicMock()
    executor.name = "alpaca"
    executor.get_order_status = AsyncMock(return_value=BrokerOrderView(3.0, 100.0, "partially_filled"))

    session = _session([row])
    s = asyncio.run(reconcile_fills(session, asset_class="equity", executor=executor, account_id=HOUSE))
    assert s.deltas_applied == 0
    assert len(s.divergences) == 1 and "not auto-shrunk" in s.divergences[0]
    assert row.qty == 5.0


def test_broker_query_failure_counts_unknown(monkeypatch):
    _patch_tick_helpers(monkeypatch)
    row = _order_row(status="submitted")
    executor = MagicMock()
    executor.name = "alpaca"
    executor.get_order_status = AsyncMock(return_value=None)
    session = _session([row])
    s = asyncio.run(reconcile_fills(session, asset_class="equity", executor=executor, account_id=HOUSE))
    assert s.unknown == 1 and s.deltas_applied == 0


def test_terminal_rows_are_not_requeried(monkeypatch):
    _patch_tick_helpers(monkeypatch)
    row = _order_row(status="filled")
    executor = MagicMock()
    executor.name = "alpaca"
    executor.get_order_status = AsyncMock()
    session = _session([row])
    s = asyncio.run(reconcile_fills(session, asset_class="equity", executor=executor, account_id=HOUSE))
    assert s.checked == 0
    executor.get_order_status.assert_not_awaited()


# ---------------------------------------------------------------------------
# Alpaca hooks
# ---------------------------------------------------------------------------

def _alpaca(monkeypatch, fake_client):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "alpaca_api_key", "k")
    monkeypatch.setattr(cfg, "alpaca_secret", "s")
    monkeypatch.setattr(cfg, "alpaca_paper", True)
    with patch("alpaca.trading.client.TradingClient", return_value=fake_client):
        from execution.alpaca import AlpacaExecutor
        return AlpacaExecutor()


def test_alpaca_get_broker_positions(monkeypatch):
    long_pos = MagicMock(symbol="AAPL", qty="10", side="PositionSide.LONG")
    short_pos = MagicMock(symbol="TSLA", qty="3", side="PositionSide.SHORT")
    fake = MagicMock()
    fake.get_all_positions.return_value = [long_pos, short_pos]
    ex = _alpaca(monkeypatch, fake)
    out = asyncio.run(ex.get_broker_positions())
    assert out == {"AAPL": 10.0, "TSLA": -3.0}


def test_alpaca_get_broker_positions_none_on_error(monkeypatch):
    fake = MagicMock()
    fake.get_all_positions.side_effect = RuntimeError("api down")
    ex = _alpaca(monkeypatch, fake)
    assert asyncio.run(ex.get_broker_positions()) is None


def test_alpaca_get_order_status(monkeypatch):
    o = MagicMock(filled_qty="5", filled_avg_price="101.5", status="OrderStatus.PARTIALLY_FILLED")
    fake = MagicMock()
    fake.get_order_by_id.return_value = o
    ex = _alpaca(monkeypatch, fake)
    view = asyncio.run(ex.get_order_status("brk-1"))
    assert view == BrokerOrderView(5.0, 101.5, "partially_filled")


def test_alpaca_get_order_status_none_on_error(monkeypatch):
    fake = MagicMock()
    fake.get_order_by_id.side_effect = RuntimeError("404")
    ex = _alpaca(monkeypatch, fake)
    assert asyncio.run(ex.get_order_status("brk-1")) is None


def test_summary_log_silent_when_unsupported():
    log = MagicMock()
    FillReconcileSummary(asset_class="equity", supported=False).log(log)
    log.info.assert_not_called()
