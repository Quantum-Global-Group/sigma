"""Persist the in-memory options decision audit log to the database.

apps/worker/options_tick.py builds a `risk.audit_log.AuditLog` per tick (full
provenance: data → features → signal → risk → gates → order) but historically
discarded it. This writes those records to the `audit_records` table so every
decision — placed, skipped, or rejected — is durable and queryable.

`audit_rows` is pure (testable without a DB); `persist_audit_log` bulk-inserts.
Persistence is best-effort at the call site (never break a trading tick).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditRecord as AuditRecordRow

logger = logging.getLogger(__name__)


def _parse_ts(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def audit_rows(records: Iterable[dict]) -> list[dict]:
    """Map AuditRecord.to_dict() payloads → audit_records column dicts. Pure.

    The dataclass field `order` maps to the `order_info` column (`order` is a
    reserved word). Missing keys default sanely so partial records still persist.
    """
    rows: list[dict] = []
    for r in records:
        rows.append({
            "ts": _parse_ts(r.get("ts")),
            "asset_class": r.get("asset_class", "option"),
            "symbol": r.get("symbol", ""),
            "strategy": r.get("strategy"),
            "decision": r.get("decision", "pending"),
            "data": r.get("data") or {},
            "features": r.get("features") or {},
            "signal": r.get("signal") or {},
            "risk": r.get("risk") or {},
            "gates": r.get("gates") or [],
            "order_info": r.get("order") or {},
            "notes": r.get("notes"),
        })
    return rows


async def persist_audit_log(session: AsyncSession, audit_log) -> int:
    """Bulk-insert every record in `audit_log` into audit_records. Returns count.

    Accepts a risk.audit_log.AuditLog (uses .to_list()) or any object exposing
    a list of record dicts. The caller owns the transaction."""
    try:
        records = audit_log.to_list()
    except AttributeError:
        records = list(audit_log or [])
    rows = audit_rows(records)
    if not rows:
        return 0
    await session.execute(insert(AuditRecordRow), rows)
    return len(rows)
