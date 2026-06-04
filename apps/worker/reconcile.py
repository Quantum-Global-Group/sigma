"""Startup reconciliation — run once before the first tick.

The worker is *stateless across ticks*: `tick.tick_once` reloads open positions
and their `exit_state` from the DB every cycle, and commits Position + ExitState
+ Order atomically per tick. So "rebuilding in-memory state on boot" really means
guaranteeing the **persisted book is self-consistent** before trading resumes
after a (re)start — and, where the broker can report it, that the DB book matches
the broker's actual positions.

Two layers, in order of certainty:

1. **Self-consistency healing** (always runs, no broker needed):
     - Every OPEN position gets an `ExitState` row. Without it, the first
       post-restart exit check resets the trailing high-water mark to `entry_px`
       and clears the partial-TP flag (see `tick._exit_state_to_dict`), which can
       loosen a stop or re-take partial profit. We heal by inserting a row seeded
       from `current_px` (falling back to `entry_px`).
     - Positions with `qty <= 0` but `closed = False` are inconsistent (a fill
       brought them flat but the close flag wasn't set). We close them.

2. **Broker cross-check** (opt-in): if the executor exposes
   `async get_broker_positions() -> {symbol: qty}`, compare against the DB book
   and log divergences. Paper/sim executors don't implement it, so this layer is
   skipped and only self-consistency runs — matching the roadmap's
   "paper: just self-consistent". A `None` result also skips (treated as
   "unsupported / unavailable"); an empty dict means the broker is genuinely flat
   and *will* be flagged against any DB-open position.

Healing is deliberately conservative: it writes only the safe, unambiguous
repairs (missing exit_state, flat-but-open). Broker divergences are **surfaced,
not auto-resolved** — closing a live position or adopting an untracked one is an
operator decision, not something a boot script should do silently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select

from db.connection import AsyncSessionLocal
from db.models import ExitState, Position

logger = logging.getLogger("worker.reconcile")

# Relative tolerance for broker-vs-DB qty comparison (0.1%), with an absolute
# floor so tiny crypto quantities don't trip on float noise.
_QTY_REL_TOL = 1e-3
_QTY_ABS_TOL = 1e-6


# ---------------------------------------------------------------------------
# Pure decision layer (no IO — unit-tested directly)
# ---------------------------------------------------------------------------

@dataclass
class BookActions:
    """The safe repairs + observations derived from one book snapshot."""

    close_position_ids: list = field(default_factory=list)          # flat-but-open → close
    create_exit_state: list[tuple] = field(default_factory=list)    # (position_id, seed_high_water)
    divergences: list[str] = field(default_factory=list)            # broker mismatches (surfaced only)


def _seed_high_water(pos: Position) -> float:
    px = pos.current_px if pos.current_px is not None else pos.entry_px
    return float(px)


def reconcile_book(
    positions: Iterable[Position],
    exit_state_pids: set,
    broker_positions: Optional[dict[str, float]] = None,
) -> BookActions:
    """Decide repairs for a single asset class's open book.

    `exit_state_pids` is the set of position ids that already have an ExitState
    row. `broker_positions` is `{symbol: signed_qty}` from the broker, or `None`
    to skip the cross-check entirely.
    """
    actions = BookActions()
    db_open: dict[str, float] = {}

    for pos in positions:
        qty = float(pos.qty)
        if qty <= 0:
            # Flat at the broker/sim but never marked closed — heal it.
            actions.close_position_ids.append(pos.id)
            continue
        if pos.id not in exit_state_pids:
            actions.create_exit_state.append((pos.id, _seed_high_water(pos)))
        db_open[pos.symbol] = db_open.get(pos.symbol, 0.0) + qty

    if broker_positions is not None:
        for sym, dbqty in db_open.items():
            bqty = broker_positions.get(sym)
            if bqty is None or abs(bqty) < _QTY_ABS_TOL:
                actions.divergences.append(f"{sym}: DB open {dbqty:g} but broker flat")
            elif abs(bqty - dbqty) > max(_QTY_ABS_TOL, abs(dbqty) * _QTY_REL_TOL):
                actions.divergences.append(
                    f"{sym}: qty mismatch DB {dbqty:g} vs broker {bqty:g}"
                )
        for sym, bqty in broker_positions.items():
            if abs(bqty) > _QTY_ABS_TOL and sym not in db_open:
                actions.divergences.append(
                    f"{sym}: broker holds {bqty:g} but DB has no open position"
                )

    return actions


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@dataclass
class AssetReconcile:
    asset_class: str
    open_positions: int = 0
    closed_flat: int = 0
    healed_exit_state: int = 0
    divergences: list[str] = field(default_factory=list)


@dataclass
class ReconcileSummary:
    per_asset: list[AssetReconcile] = field(default_factory=list)

    def log(self, log: logging.Logger = logger) -> None:
        for a in self.per_asset:
            log.info(
                "[reconcile:%s] open=%d closed_flat=%d healed_exit_state=%d divergences=%d",
                a.asset_class, a.open_positions, a.closed_flat,
                a.healed_exit_state, len(a.divergences),
            )
            for d in a.divergences:
                log.warning("[reconcile:%s] divergence — %s", a.asset_class, d)


# ---------------------------------------------------------------------------
# IO layer
# ---------------------------------------------------------------------------

async def _try_broker_positions(asset_class: str) -> Optional[dict[str, float]]:
    """Fetch the broker's positions for the opt-in cross-check, or None to skip.

    Never raises: a broker query failure (or an executor that doesn't implement
    `get_broker_positions`) degrades to self-consistency-only, which is the
    correct behavior for paper/sim venues."""
    try:
        from execution import get_executor
        executor = get_executor(asset_class)
    except Exception:
        logger.warning("[reconcile:%s] no executor — self-consistent check only",
                       asset_class, exc_info=True)
        return None

    fetch = getattr(executor, "get_broker_positions", None)
    if not callable(fetch):
        return None  # unsupported (paper/sim) — skip the cross-check
    try:
        raw = await fetch()
    except Exception:
        logger.warning("[reconcile:%s] broker position query failed — self-consistent check only",
                       asset_class, exc_info=True)
        return None
    if raw is None:
        return None
    return {str(s): float(q) for s, q in raw.items()}


async def _reconcile_asset_class(session, asset_class: str) -> AssetReconcile:
    res = await session.execute(
        select(Position)
        .where(Position.asset_class == asset_class)
        .where(Position.closed.is_(False))
    )
    positions = list(res.scalars().all())
    summary = AssetReconcile(asset_class=asset_class, open_positions=len(positions))
    if not positions:
        return summary

    pids = [p.id for p in positions]
    es_res = await session.execute(
        select(ExitState.position_id).where(ExitState.position_id.in_(pids))
    )
    es_pids = set(es_res.scalars().all())

    broker_positions = await _try_broker_positions(asset_class)
    actions = reconcile_book(positions, es_pids, broker_positions)

    now = datetime.now(timezone.utc)
    posmap = {p.id: p for p in positions}
    for pid in actions.close_position_ids:
        p = posmap[pid]
        p.qty = 0.0
        p.closed = True
        p.closed_at = now
        p.updated_at = now
    for pid, seed in actions.create_exit_state:
        session.add(ExitState(position_id=pid, high_water_px=seed))

    summary.closed_flat = len(actions.close_position_ids)
    summary.healed_exit_state = len(actions.create_exit_state)
    summary.divergences = actions.divergences
    # Open count after healing excludes the flat rows we just closed.
    summary.open_positions = len(positions) - summary.closed_flat
    return summary


async def reconcile_startup(asset_classes: Iterable[str]) -> ReconcileSummary:
    """Reconcile the persisted book for each asset class before the first tick.

    One session, one commit. Safe to call on every boot — all repairs are
    idempotent (a healed book yields zero further changes on the next run)."""
    summary = ReconcileSummary()
    async with AsyncSessionLocal() as session:
        for ac in asset_classes:
            summary.per_asset.append(await _reconcile_asset_class(session, ac))
        await session.commit()
    return summary
