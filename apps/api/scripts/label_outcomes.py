#!/usr/bin/env python
"""
Backfill realized outcomes onto past signals — the self-evolution feedback step.

Usage:
    python scripts/label_outcomes.py [--asset-class equity] [--horizon-bars 5]

Reads unlabeled signal_history rows, looks up the forward price move from the
candles table, and writes realized_return + outcome. Idempotent: only touches
rows where labeled_at IS NULL and whose forward window has elapsed. Normally run
by the worker-internal scheduler (apps/worker/scheduler.py); this CLI is for
manual/cron runs and debugging.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from db.connection import AsyncSessionLocal
from ml.labeling import label_outcomes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("label_outcomes")


async def _run(asset_classes: list[str], horizon_bars: int | None) -> None:
    async with AsyncSessionLocal() as session:
        total = 0
        for ac in asset_classes:
            total += await label_outcomes(session, ac, horizon_bars=horizon_bars)
        await session.commit()
        logger.info("Labeled %d signals across %s", total, asset_classes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-class", action="append", dest="asset_classes",
                        help="Repeatable; defaults to crypto,equity,forex,option")
    parser.add_argument("--horizon-bars", type=int, default=None)
    args = parser.parse_args()
    asset_classes = args.asset_classes or ["crypto", "equity", "forex", "option"]
    asyncio.run(_run(asset_classes, args.horizon_bars))


if __name__ == "__main__":
    main()
