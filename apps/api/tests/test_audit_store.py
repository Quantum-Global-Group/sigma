"""Audit-persistence tests (PR-D) — pure row mapping + bulk insert via mock session."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from db.audit_store import audit_rows, persist_audit_log
from risk.audit_log import AuditLog


# ---------------------------------------------------------------------------
# audit_rows (pure)
# ---------------------------------------------------------------------------

def test_audit_rows_maps_order_to_order_info():
    records = [{
        "symbol": "AAPL", "asset_class": "option", "ts": "2026-01-02T00:00:00+00:00",
        "strategy": "long_call", "decision": "placed",
        "data": {"spot": 150.0}, "features": {"iv_rank": 0.6}, "signal": {"direction": "BUY"},
        "risk": {"contracts": 2}, "gates": [{"gate": "G1_data", "passed": True}],
        "order": {"client_order_id": "x", "qty": 2}, "notes": None,
    }]
    rows = audit_rows(records)
    assert len(rows) == 1
    r = rows[0]
    assert r["order_info"] == {"client_order_id": "x", "qty": 2}   # order → order_info
    assert "order" not in r
    assert r["symbol"] == "AAPL" and r["strategy"] == "long_call" and r["decision"] == "placed"
    assert isinstance(r["ts"], datetime)
    assert r["gates"] == [{"gate": "G1_data", "passed": True}]


def test_audit_rows_defaults_missing_fields():
    rows = audit_rows([{"symbol": "MSFT"}])
    r = rows[0]
    assert r["asset_class"] == "option" and r["decision"] == "pending"
    assert r["data"] == {} and r["gates"] == [] and r["order_info"] == {}
    assert isinstance(r["ts"], datetime)


def test_audit_rows_bad_ts_falls_back_to_now():
    rows = audit_rows([{"symbol": "X", "ts": "not-a-date"}])
    assert isinstance(rows[0]["ts"], datetime)


# ---------------------------------------------------------------------------
# persist_audit_log (mock session)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_audit_log_inserts_records():
    log = AuditLog()
    rec = log.new("AAPL", asset_class="option")
    rec.gate("G1_data", True).finalize("placed", client_order_id="abc", qty=1)
    log.new("MSFT").finalize("skipped")

    session = AsyncMock()
    n = await persist_audit_log(session, log)
    assert n == 2
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_audit_log_empty_is_noop():
    session = AsyncMock()
    n = await persist_audit_log(session, AuditLog())
    assert n == 0
    session.execute.assert_not_awaited()
