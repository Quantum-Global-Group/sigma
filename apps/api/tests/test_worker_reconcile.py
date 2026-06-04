"""Tests for apps/worker/reconcile.py — startup book reconciliation.

The pure decision layer (`reconcile_book`) is exercised directly with in-memory
Position objects (no DB). The IO wrapper (`_reconcile_asset_class`) and the
opt-in broker hook (`_try_broker_positions`) are tested with mocks, mirroring
test_worker_tick.py.
"""

import sys
import uuid
from pathlib import Path

# apps/api on path (config, db.*, execution); apps/worker for reconcile.py
_api = Path(__file__).parents[1]
_worker = _api.parent / "worker"
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_worker))

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from reconcile import (
    AssetReconcile,
    ReconcileSummary,
    _reconcile_asset_class,
    _try_broker_positions,
    reconcile_book,
)
from db.models import Position


def _pos(symbol="AAPL", qty=10.0, entry_px=100.0, current_px=110.0, pid=None) -> Position:
    return Position(
        id=pid or uuid.uuid4(),
        asset_class="equity",
        symbol=symbol,
        qty=qty,
        entry_px=entry_px,
        current_px=current_px,
        closed=False,
    )


# ---------------------------------------------------------------------------
# reconcile_book — self-consistency (no broker)
# ---------------------------------------------------------------------------

def test_open_position_without_exit_state_is_healed():
    p = _pos()
    actions = reconcile_book([p], exit_state_pids=set())
    assert actions.create_exit_state == [(p.id, 110.0)]   # seeded from current_px
    assert actions.close_position_ids == []
    assert actions.divergences == []


def test_open_position_with_exit_state_is_left_alone():
    p = _pos()
    actions = reconcile_book([p], exit_state_pids={p.id})
    assert actions.create_exit_state == []
    assert actions.close_position_ids == []


def test_exit_state_seed_falls_back_to_entry_px_when_no_current_px():
    p = _pos(current_px=None, entry_px=99.0)
    actions = reconcile_book([p], exit_state_pids=set())
    assert actions.create_exit_state == [(p.id, 99.0)]


def test_flat_but_open_position_is_closed_not_healed():
    p = _pos(qty=0.0)
    actions = reconcile_book([p], exit_state_pids=set())
    assert actions.close_position_ids == [p.id]
    assert actions.create_exit_state == []   # don't seed exit_state for a flat row


def test_negative_qty_treated_as_flat():
    p = _pos(qty=-5.0)
    actions = reconcile_book([p], exit_state_pids=set())
    assert actions.close_position_ids == [p.id]


def test_mixed_book():
    healthy = _pos(symbol="MSFT", pid=uuid.uuid4())
    needs_es = _pos(symbol="NVDA", pid=uuid.uuid4())
    flat = _pos(symbol="TSLA", qty=0.0, pid=uuid.uuid4())
    actions = reconcile_book([healthy, needs_es, flat], exit_state_pids={healthy.id})
    assert actions.create_exit_state == [(needs_es.id, 110.0)]
    assert actions.close_position_ids == [flat.id]


# ---------------------------------------------------------------------------
# reconcile_book — broker cross-check
# ---------------------------------------------------------------------------

def test_broker_match_no_divergence():
    p = _pos(symbol="AAPL", qty=10.0)
    actions = reconcile_book([p], {p.id}, broker_positions={"AAPL": 10.0})
    assert actions.divergences == []


def test_broker_flat_but_db_open_flagged():
    p = _pos(symbol="AAPL", qty=10.0)
    actions = reconcile_book([p], {p.id}, broker_positions={})
    assert len(actions.divergences) == 1
    assert "DB open 10 but broker flat" in actions.divergences[0]


def test_broker_qty_mismatch_flagged():
    p = _pos(symbol="AAPL", qty=10.0)
    actions = reconcile_book([p], {p.id}, broker_positions={"AAPL": 7.0})
    assert len(actions.divergences) == 1
    assert "qty mismatch" in actions.divergences[0]


def test_broker_holds_untracked_symbol_flagged():
    p = _pos(symbol="AAPL", qty=10.0)
    actions = reconcile_book([p], {p.id}, broker_positions={"AAPL": 10.0, "GOOG": 3.0})
    assert len(actions.divergences) == 1
    assert "GOOG" in actions.divergences[0] and "no open position" in actions.divergences[0]


def test_flat_db_row_not_double_counted_against_broker():
    # A flat-but-open DB row is being closed, so the broker correctly not
    # holding it must NOT be reported as a divergence.
    flat = _pos(symbol="AAPL", qty=0.0)
    actions = reconcile_book([flat], set(), broker_positions={})
    assert actions.divergences == []
    assert actions.close_position_ids == [flat.id]


def test_qty_within_tolerance_not_flagged():
    p = _pos(symbol="ETH-USD", qty=1.0)
    actions = reconcile_book([p], {p.id}, broker_positions={"ETH-USD": 1.0 + 1e-9})
    assert actions.divergences == []


# ---------------------------------------------------------------------------
# _try_broker_positions — opt-in hook
# ---------------------------------------------------------------------------

def test_try_broker_positions_skips_when_unsupported(monkeypatch):
    import execution
    executor = MagicMock(spec=[])  # no get_broker_positions attribute
    monkeypatch.setattr(execution, "get_executor", lambda ac: executor)
    assert asyncio.run(_try_broker_positions("equity")) is None


def test_try_broker_positions_returns_dict(monkeypatch):
    import execution
    executor = MagicMock()
    executor.get_broker_positions = AsyncMock(return_value={"AAPL": 10})
    monkeypatch.setattr(execution, "get_executor", lambda ac: executor)
    assert asyncio.run(_try_broker_positions("equity")) == {"AAPL": 10.0}


def test_try_broker_positions_none_result_skips(monkeypatch):
    import execution
    executor = MagicMock()
    executor.get_broker_positions = AsyncMock(return_value=None)
    monkeypatch.setattr(execution, "get_executor", lambda ac: executor)
    assert asyncio.run(_try_broker_positions("equity")) is None


def test_try_broker_positions_swallows_query_error(monkeypatch):
    import execution
    executor = MagicMock()
    executor.get_broker_positions = AsyncMock(side_effect=RuntimeError("api down"))
    monkeypatch.setattr(execution, "get_executor", lambda ac: executor)
    assert asyncio.run(_try_broker_positions("equity")) is None


def test_try_broker_positions_skips_when_executor_construction_fails(monkeypatch):
    import execution

    def boom(ac):
        raise ValueError("missing creds")

    monkeypatch.setattr(execution, "get_executor", boom)
    assert asyncio.run(_try_broker_positions("crypto")) is None


# ---------------------------------------------------------------------------
# _reconcile_asset_class — IO wrapper applies the repairs
# ---------------------------------------------------------------------------

def _session_returning(positions, es_pids):
    """A mock async session whose two execute() calls return positions then
    exit_state pids."""
    pos_result = MagicMock()
    pos_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=positions)))
    es_result = MagicMock()
    es_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=es_pids)))
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[pos_result, es_result])
    session.add = MagicMock()
    return session


def test_reconcile_asset_class_heals_and_closes(monkeypatch):
    import reconcile
    monkeypatch.setattr(reconcile, "_try_broker_positions", AsyncMock(return_value=None))

    needs_es = _pos(symbol="NVDA")
    flat = _pos(symbol="TSLA", qty=0.0)
    session = _session_returning([needs_es, flat], es_pids=[])

    summary = asyncio.run(_reconcile_asset_class(session, "equity"))

    assert isinstance(summary, AssetReconcile)
    assert summary.closed_flat == 1
    assert summary.healed_exit_state == 1
    assert summary.open_positions == 1          # 2 loaded − 1 closed
    # flat row closed
    assert flat.closed is True and float(flat.qty) == 0.0 and flat.closed_at is not None
    # one ExitState added for the un-stated open position
    assert session.add.call_count == 1


def test_reconcile_asset_class_empty_book_is_noop(monkeypatch):
    import reconcile
    monkeypatch.setattr(reconcile, "_try_broker_positions", AsyncMock(return_value=None))
    session = _session_returning([], es_pids=[])
    # second execute() is never reached for an empty book
    session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
    ))
    summary = asyncio.run(_reconcile_asset_class(session, "equity"))
    assert summary.open_positions == 0
    assert summary.healed_exit_state == 0
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# ReconcileSummary.log
# ---------------------------------------------------------------------------

def test_summary_log_emits_per_asset_and_divergences():
    log = MagicMock()
    summary = ReconcileSummary(per_asset=[
        AssetReconcile("equity", open_positions=2, closed_flat=1,
                       healed_exit_state=1, divergences=["AAPL: DB open 10 but broker flat"]),
    ])
    summary.log(log)
    assert log.info.call_count == 1
    assert log.warning.call_count == 1
