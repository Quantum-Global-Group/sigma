"""Outcome labeling — close the loop between predictions and what happened.

Every `signal_history` row is a prediction (signal, confidence, predicted_return,
model_version). This job revisits each unlabeled prediction once the forward
window has elapsed, looks up the actual forward price move from the persisted
`candles` table, and records `realized_return` + `outcome` (win|loss|flat).

Labeling from candle forward-return (not trade P&L) measures *model* accuracy
directly and covers HOLD / no-trade signals too — exactly what the evaluation +
promotion steps need. The pure helpers (`classify_outcome`,
`compute_realized_return`) are unit-tested; the DB orchestration is injectable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import Candle, SignalHistory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def compute_realized_return(entry_close: float, exit_close: float) -> float:
    if entry_close <= 0:
        return 0.0
    return (exit_close - entry_close) / entry_close


def classify_outcome(signal: str, realized_return: float, flat_threshold: float) -> str:
    """win|loss|flat from the signal's directional call vs the realized move.

    BUY wants up, SELL wants down. HOLD and sub-threshold moves are 'flat'
    (no actionable directional outcome) — the evaluator scores hit-rate over
    non-flat rows."""
    sig = (signal or "").upper()
    if abs(realized_return) < flat_threshold or sig == "HOLD":
        return "flat"
    moved_up = realized_return > 0
    if sig == "BUY":
        return "win" if moved_up else "loss"
    if sig == "SELL":
        return "win" if not moved_up else "loss"
    return "flat"


# ---------------------------------------------------------------------------
# DB orchestration
# ---------------------------------------------------------------------------

# (entry_close, exit_close) or None when the forward window hasn't filled yet.
PriceFetch = Callable[[AsyncSession, str, str, str, datetime, int], Awaitable[Optional[tuple[float, float]]]]


async def _fetch_prices(
    session: AsyncSession, asset_class: str, ticker: str, timeframe: str,
    signal_ts: datetime, horizon_bars: int,
) -> Optional[tuple[float, float]]:
    """Entry close at/just-before the signal, and the close `horizon_bars` later.
    None if the forward bars don't exist yet (leave the row unlabeled)."""
    entry = (
        select(Candle.close)
        .where(Candle.asset_class == asset_class, Candle.symbol == ticker,
               Candle.timeframe == timeframe, Candle.ts <= signal_ts)
        .order_by(Candle.ts.desc()).limit(1)
    )
    entry_close = (await session.execute(entry)).scalar_one_or_none()
    if entry_close is None:
        return None

    exit_q = (
        select(Candle.close)
        .where(Candle.asset_class == asset_class, Candle.symbol == ticker,
               Candle.timeframe == timeframe, Candle.ts > signal_ts)
        .order_by(Candle.ts.asc()).offset(max(0, horizon_bars - 1)).limit(1)
    )
    exit_close = (await session.execute(exit_q)).scalar_one_or_none()
    if exit_close is None:
        return None
    return float(entry_close), float(exit_close)


async def _unlabeled_signals(session: AsyncSession, asset_class: str, limit: int) -> list[SignalHistory]:
    q = (
        select(SignalHistory)
        .where(SignalHistory.asset_class == asset_class)
        .where(SignalHistory.labeled_at.is_(None))
        .order_by(SignalHistory.created_at.asc())
        .limit(limit)
    )
    return list((await session.execute(q)).scalars().all())


async def label_outcomes(
    session: AsyncSession,
    asset_class: str,
    *,
    horizon_bars: Optional[int] = None,
    flat_threshold: Optional[float] = None,
    limit: int = 5000,
    fetch_prices: Optional[PriceFetch] = None,
) -> int:
    """Label unlabeled signals for `asset_class`. Returns rows labeled.

    Skips rows whose forward window hasn't filled yet (they stay unlabeled and
    get picked up on a later run). The caller owns the transaction."""
    horizon = horizon_bars if horizon_bars is not None else settings.label_horizon_bars
    flat = flat_threshold if flat_threshold is not None else settings.label_flat_threshold
    fetch = fetch_prices or _fetch_prices

    rows = await _unlabeled_signals(session, asset_class, limit)
    now = datetime.now(timezone.utc)
    labeled = 0
    for sig in rows:
        prices = await fetch(session, asset_class, sig.ticker, sig.timeframe, sig.created_at, horizon)
        if prices is None:
            continue
        entry_close, exit_close = prices
        rr = compute_realized_return(entry_close, exit_close)
        sig.realized_return = rr
        sig.outcome = classify_outcome(sig.signal, rr, flat)
        sig.labeled_at = now
        labeled += 1
    logger.info("[label] %s: labeled %d/%d unlabeled signals", asset_class, labeled, len(rows))
    return labeled
