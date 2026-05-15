"""Open + recently-closed positions for the worker's house book.

Read-only — these endpoints are intended for the dashboard and ops, not for
multi-tenant trading. The worker mutates positions; clients observe."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from db.models import Position
from middleware.auth import AuthContext, require_auth

router = APIRouter(prefix="/positions", tags=["positions"])
AuthDep = Annotated[AuthContext, Depends(require_auth)]


class PositionOut(BaseModel):
    id: str
    asset_class: str
    symbol: str
    qty: float
    entry_px: float
    entry_ts: datetime
    current_px: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: float
    closed: bool
    closed_at: Optional[datetime] = None


@router.get("", response_model=list[PositionOut])
async def list_positions(
    auth: AuthDep,
    asset_class: Optional[str] = Query(None, pattern="^(equity|crypto)$"),
    open_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(Position).order_by(Position.entry_ts.desc()).limit(limit)
    if asset_class:
        q = q.where(Position.asset_class == asset_class)
    if open_only:
        q = q.where(Position.closed.is_(False))

    res = await db.execute(q)
    return [
        PositionOut(
            id=str(row.id),
            asset_class=row.asset_class,
            symbol=row.symbol,
            qty=float(row.qty),
            entry_px=float(row.entry_px),
            entry_ts=row.entry_ts,
            current_px=float(row.current_px) if row.current_px is not None else None,
            unrealized_pnl=float(row.unrealized_pnl) if row.unrealized_pnl is not None else None,
            realized_pnl=float(row.realized_pnl),
            closed=row.closed,
            closed_at=row.closed_at,
        )
        for row in res.scalars().all()
    ]
