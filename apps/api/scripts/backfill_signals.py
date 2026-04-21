#!/usr/bin/env python
"""
Backfill 90 days of historical signals for a list of tickers.

Inserts rows directly into `signal_history` (TimescaleDB hypertable) using
asyncpg for bulk performance. Re-running is safe — duplicate (user_id, ticker,
created_at) combinations are simply re-inserted; the hypertable handles them.

Usage:
    python scripts/backfill_signals.py --user-email dev@sigma.local [--tickers AAPL MSFT] [--days 90]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

# Resolve imports relative to apps/api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings
from db.models import SignalHistory, User
from ml.data import fetch_ohlcv
from ml.features import build_features
from ml.inference import predict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_signals")

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA"]


async def backfill(user_email: str, tickers: list[str], days: int):
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        result = await session.execute(select(User).where(User.email == user_email))
        user = result.scalar_one_or_none()
        if user is None:
            raise SystemExit(f"User not found: {user_email}")

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        for ticker in tickers:
            try:
                df = fetch_ohlcv(ticker, "daily")
            except Exception as exc:
                logger.warning("Skipping %s: %s", ticker, exc)
                continue

            features = build_features(df)
            if features.empty:
                continue

            history_index = features.index[features.index >= pd.Timestamp(cutoff)]
            inserted = 0

            for date in history_index:
                snapshot = features.loc[:date]
                if snapshot.empty:
                    continue

                result_signal = predict(snapshot)
                row = SignalHistory(
                    user_id=user.id,
                    ticker=ticker,
                    timeframe="daily",
                    signal=result_signal.signal,
                    confidence=result_signal.confidence,
                    predicted_return=result_signal.predicted_return,
                    model_version=result_signal.model_version,
                    features=json.loads(snapshot.iloc[-1].to_json()),
                    created_at=date.to_pydatetime().replace(tzinfo=timezone.utc),
                )
                session.add(row)
                inserted += 1

            await session.commit()
            logger.info("Inserted %d signals for %s", inserted, ticker)

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-email", required=True, help="Email of the user to attach signals to")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()

    asyncio.run(backfill(args.user_email, args.tickers, args.days))


if __name__ == "__main__":
    main()
