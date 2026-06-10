"""Recent orders / fills for the worker's house book."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from db.models import Order
from middleware.auth import AuthContext, require_auth

router = APIRouter(prefix="/orders", tags=["orders"])
AuthDep = Annotated[AuthContext, Depends(require_auth)]


class OrderOut(BaseModel):
    id: str
    account_id: Optional[str] = None
    asset_class: str
    symbol: str
    ts: datetime
    side: str
    qty: float
    px: float
    fee: float
    slippage_bps: Optional[float] = None
    executor: str
    external_id: Optional[str] = None
    status: str


@router.get("", response_model=list[OrderOut])
async def list_orders(
    auth: AuthDep,
    asset_class: Optional[str] = Query(None, pattern="^(equity|crypto|option|forex)$"),
    account_id: Optional[str] = Query(None, description="Filter to one trading account (UUID)"),
    symbol: Optional[str] = Query(None, max_length=32),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(Order).order_by(Order.ts.desc()).limit(limit)
    if asset_class:
        q = q.where(Order.asset_class == asset_class)
    if account_id:
        q = q.where(Order.account_id == account_id)
    if symbol:
        q = q.where(Order.symbol == symbol.upper())

    res = await db.execute(q)
    return [
        OrderOut(
            id=str(row.id),
            account_id=str(row.account_id) if getattr(row, "account_id", None) else None,
            asset_class=row.asset_class,
            symbol=row.symbol,
            ts=row.ts,
            side=row.side,
            qty=float(row.qty),
            px=float(row.px),
            fee=float(row.fee),
            slippage_bps=float(row.slippage_bps) if row.slippage_bps is not None else None,
            executor=row.executor,
            external_id=row.external_id,
            status=row.status,
        )
        for row in res.scalars().all()
    ]
