"""Candle persistence — durable OHLCV harnessing for backfill + training.

The worker fetches OHLCV every tick and (historically) discarded it. This
module upserts the most-recent bars into the `candles` hypertable so the data
is reusable: model training, backfills, and audit all read the exact bars the
worker traded on.

`upsert_candles` is idempotent (PostgreSQL ON CONFLICT DO UPDATE on the candles
PK) and TimescaleDB-safe (the conflict target includes the `ts` partition key).
Only the tail of the frame is written each call — re-fetching the same window
every tick would otherwise rewrite hundreds of rows; the upsert gap-fills
instead. Persistence must never break a trading tick, so callers wrap this in a
try/except (see worker.tick).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Candle

logger = logging.getLogger(__name__)

_OHLCV = ("open", "high", "low", "close", "volume")


def _to_utc(ts) -> Optional[datetime]:
    """Coerce a pandas index value to a tz-aware UTC datetime."""
    try:
        t = pd.Timestamp(ts)
    except (ValueError, TypeError):
        return None
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.to_pydatetime()


def rows_from_df(
    asset_class: str,
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    source: str,
    tail: int,
) -> list[dict]:
    """Build candle rows (dicts) from the tail of an OHLCV frame. Pure/testable.

    Skips rows with a non-parseable timestamp or missing OHLCV columns. Returns
    an empty list for an empty/short frame or one missing required columns.
    """
    if df is None or df.empty:
        return []
    missing = [c for c in _OHLCV if c not in df.columns]
    if missing:
        logger.debug("candle persist skipped for %s: missing %s", symbol, missing)
        return []

    sub = df.tail(max(1, tail))
    rows: list[dict] = []
    for idx, r in sub.iterrows():
        ts = _to_utc(idx)
        if ts is None:
            continue
        try:
            rows.append({
                "asset_class": asset_class,
                "symbol": symbol,
                "timeframe": timeframe,
                "ts": ts,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
                "source": source,
            })
        except (TypeError, ValueError):
            continue
    return rows


async def upsert_candles(
    session: AsyncSession,
    *,
    asset_class: str,
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    source: str = "worker",
    tail: int = 20,
) -> int:
    """Upsert the tail of `df` into the candles table. Returns rows written.

    Idempotent: re-running with overlapping bars updates in place. The caller
    owns the transaction (the worker commits at the end of its tick)."""
    rows = rows_from_df(asset_class, symbol, timeframe, df, source, tail)
    if not rows:
        return 0

    stmt = insert(Candle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["asset_class", "symbol", "timeframe", "ts"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "source": stmt.excluded.source,
        },
    )
    await session.execute(stmt)
    return len(rows)
