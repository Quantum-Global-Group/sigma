"""Partial-fill reconciliation — pull the broker's fill truth into the book.

`executor.place()` polls for a fill only up to `*_order_timeout_seconds`. A DAY
order that hasn't (fully) filled by then **keeps working at the broker**: the
worker recorded `qty=0` (or a partial qty) in `orders` and moved on, while the
broker keeps filling. Without reconciliation the DB position under-counts what
the account actually holds — silently, until an exit sells the wrong size.

This runs at the start of every tick, before the book is loaded:

1. Select recent non-terminal `orders` rows for this (account, asset_class)
   that carry a broker `external_id` and were placed by this executor.
2. Ask the broker for its current view (`executor.get_order_status`, an opt-in
   hook — paper/sim executors fill synchronously and don't implement it).
3. Apply the **delta** (broker cumulative fill − recorded fill) to the position
   via tick's own `_apply_fill_to_position`, at the tranche price implied by
   the cumulative averages — so DB avg-px converges exactly to the broker's.
4. Sync the order row (qty / px / status) so terminal orders stop being
   re-queried.

All decisions are pure functions; the IO wrapper never guesses — a failed
broker query skips the order, and a broker reporting *less* than the DB is
surfaced as a divergence, never auto-shrunk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Order, Position
from execution.base import BrokerOrderView, Side

logger = logging.getLogger("worker.fill_reconcile")

_QTY_EPS = 1e-9

# Order statuses that can never fill further — anything else gets re-queried.
TERMINAL_STATUSES = {"filled", "canceled", "cancelled", "expired", "rejected", "done"}

# How far back to look for stragglers. DAY orders die at the close, so two
# sessions is generous; older non-terminal rows are stale bookkeeping, not
# live orders.
DEFAULT_LOOKBACK_HOURS = 48


def is_terminal(status: str) -> bool:
    return str(status or "").lower().split(".")[-1] in TERMINAL_STATUSES


def compute_fill_delta(
    db_qty: float, db_px: float, view: BrokerOrderView
) -> Optional[tuple[float, float]]:
    """(delta_qty, delta_px) to apply, or None when there's nothing to do.

    `delta_px` is the implied price of the unrecorded tranche, derived from
    the cumulative averages: applying (delta_qty @ delta_px) on top of
    (db_qty @ db_px) lands the position exactly on the broker's
    (filled_qty @ avg_price). Falls back to the cumulative average (then the
    DB price) when the implied price is degenerate."""
    delta = float(view.filled_qty) - float(db_qty)
    if delta <= _QTY_EPS:
        return None

    avg = float(view.avg_price) if view.avg_price else 0.0
    if avg > 0:
        if db_qty > _QTY_EPS and db_px > 0:
            implied = (view.filled_qty * avg - db_qty * db_px) / delta
            delta_px = implied if implied > 0 else avg
        else:
            delta_px = avg
    elif db_px > 0:
        delta_px = float(db_px)
    else:
        return None  # no usable price anywhere — don't fabricate one
    return delta, delta_px


@dataclass
class FillReconcileSummary:
    asset_class: str
    supported: bool = True
    checked: int = 0
    deltas_applied: int = 0
    status_synced: int = 0
    unknown: int = 0          # broker query failed / returned None
    divergences: list[str] = field(default_factory=list)

    def log(self, log: logging.Logger = logger) -> None:
        if not self.supported:
            return  # paper/sim — nothing to say every tick
        if self.checked or self.divergences:
            log.info(
                "[fill-reconcile:%s] checked=%d deltas=%d status_synced=%d unknown=%d",
                self.asset_class, self.checked, self.deltas_applied,
                self.status_synced, self.unknown,
            )
        for d in self.divergences:
            log.warning("[fill-reconcile:%s] divergence — %s", self.asset_class, d)


async def reconcile_fills(
    session: AsyncSession,
    *,
    asset_class: str,
    executor,
    account_id,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
) -> FillReconcileSummary:
    """Reconcile recent non-terminal orders against the broker. Never raises
    business errors upward — a broker hiccup degrades to "checked next tick"."""
    summary = FillReconcileSummary(asset_class=asset_class)

    fetch = getattr(executor, "get_order_status", None)
    if not callable(fetch):
        summary.supported = False
        return summary

    executor_name = getattr(executor, "name", "unknown")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    res = await session.execute(
        select(Order)
        .where(Order.account_id == account_id)
        .where(Order.asset_class == asset_class)
        .where(Order.executor == executor_name)
        .where(Order.external_id.is_not(None))
        .where(Order.ts >= cutoff)
    )
    stale = [o for o in res.scalars().all() if not is_terminal(o.status)]
    if not stale:
        return summary

    # Imported lazily: tick imports this module at call time, and we reuse its
    # position math so BUY-blend / SELL-reduce semantics exist in one place.
    from worker.tick import _apply_fill_to_position, _ensure_exit_state

    for row in stale:
        summary.checked += 1
        view = await fetch(row.external_id)
        if view is None:
            summary.unknown += 1
            continue

        db_qty = float(row.qty)
        if view.filled_qty < db_qty - _QTY_EPS:
            summary.divergences.append(
                f"{row.symbol} order {row.external_id}: broker filled {view.filled_qty:g} "
                f"< recorded {db_qty:g} — not auto-shrunk, inspect manually"
            )
            continue

        delta = compute_fill_delta(db_qty, float(row.px), view)
        if delta is not None:
            dqty, dpx = delta
            side = Side.BUY if str(row.side).lower() == "buy" else Side.SELL
            pos_res = await session.execute(
                select(Position)
                .where(Position.account_id == account_id)
                .where(Position.asset_class == asset_class)
                .where(Position.symbol == row.symbol)
                .where(Position.closed.is_(False))
            )
            existing = pos_res.scalars().first()
            if side == Side.SELL and existing is None:
                summary.divergences.append(
                    f"{row.symbol} order {row.external_id}: late SELL fill {dqty:g} "
                    f"but no open position to reduce"
                )
            else:
                affected = await _apply_fill_to_position(
                    session,
                    asset_class=asset_class,
                    symbol=row.symbol,
                    side=side,
                    qty=dqty,
                    price=dpx,
                    existing=existing,
                )
                if side == Side.BUY and affected is not None and not affected.closed:
                    await _ensure_exit_state(session, affected.id, seed_high_water=dpx)
                row.qty = view.filled_qty
                if view.avg_price:
                    row.px = view.avg_price
                summary.deltas_applied += 1
                logger.info(
                    "[fill-reconcile:%s] %s %s late fill applied: +%g @ %g (broker total %g)",
                    asset_class, row.symbol, row.side, dqty, dpx, view.filled_qty,
                )

        # Always sync the status so terminal orders stop being re-queried.
        if view.status and view.status != row.status:
            row.status = view.status
            summary.status_synced += 1

    return summary
