"""DB-backed order idempotency.

tradeFlux kept idempotency in a JSON file (`~/.tradeflux/alpaca_idempotency.json`).
sigma is Postgres + a single long-running worker, so the durable, restart-safe
place for this is the `orders` table: the `client_order_id` UNIQUE index (see
migration 007) is the source of truth.

`already_submitted` lets the worker check before placing, and the DB unique
constraint is the hard backstop if two attempts race."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Order


async def already_submitted(
    session: AsyncSession, client_order_id: str, account_id=None
) -> Optional[Order]:
    """Return the existing Order for this client_order_id, or None.

    The unique index is scoped per account (migration 013): pass `account_id`
    to check within one account's book — two accounts may legitimately share a
    client_order_id string for the same logical order. `None` preserves the
    legacy global check (single house book)."""
    if not client_order_id:
        return None
    q = select(Order).where(Order.client_order_id == client_order_id)
    if account_id is not None:
        q = q.where(Order.account_id == account_id)
    res = await session.execute(q)
    return res.scalar_one_or_none()
