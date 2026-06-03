#!/usr/bin/env python
"""Embed labeled signal_history rows into signal_embeddings (pgvector).

Builds a fixed 64-dim numeric vector from component_weights + key features —
no GPU model required for the MVP. Run manually or via the worker scheduler
when EMBED_SIGNALS_ENABLED=true.

Usage:
    cd apps/api
    PYTHONPATH=. python scripts/embed_signals.py
    PYTHONPATH=. python scripts/embed_signals.py --asset-class equity --limit 500
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from db.connection import AsyncSessionLocal
from db.models import SignalHistory
from ml.embeddings import EMBEDDING_DIM, build_embedding_vector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("embed_signals")

# Canonical strategy slot order — unknown strategies hash into spare dims.
_STRATEGY_SLOTS = (
    "momentum", "mean_reversion", "breakout", "regime", "ml",
    "macd", "fourier", "gbm", "ou", "heston", "ict",
)


async def embed_unlabeled(
    session: AsyncSession,
    *,
    asset_class: str | None = None,
    limit: int = 1000,
) -> int:
    """Insert embeddings for labeled rows not yet embedded. Returns count inserted."""
    subq = select(SignalHistory.id).where(SignalHistory.labeled_at.isnot(None))
    if asset_class:
        subq = subq.where(SignalHistory.asset_class == asset_class)
    subq = subq.order_by(SignalHistory.created_at.desc()).limit(limit)

    rows = list((await session.execute(subq)).scalars().all())
    if not rows:
        return 0

    # Skip rows that already have an embedding.
    existing_q = text(
        "SELECT signal_history_id FROM signal_embeddings "
        "WHERE signal_history_id = ANY(:ids) AND signal_history_id IS NOT NULL",
    )
    existing_res = await session.execute(existing_q, {"ids": rows})
    already = {r[0] for r in existing_res.all()}
    todo_ids = [i for i in rows if i not in already]
    if not todo_ids:
        return 0

    hist_q = select(SignalHistory).where(SignalHistory.id.in_(todo_ids))
    signals = list((await session.execute(hist_q)).scalars().all())

    inserted = 0
    for sh in signals:
        vec = build_embedding_vector(sh, strategy_slots=_STRATEGY_SLOTS)
        cw = sh.component_weights or {}
        comp = cw.get("component_signals") or {}
        insert_sql = text("""
            INSERT INTO signal_embeddings
              (signal_history_id, asset_class, symbol, ts, features, component_signals, outcome, embedding)
            VALUES
              (:signal_history_id, :asset_class, :symbol, :ts, :features::jsonb,
               :component_signals::jsonb, :outcome, :embedding::vector)
        """)
        await session.execute(insert_sql, {
            "signal_history_id": sh.id,
            "asset_class": sh.asset_class or "equity",
            "symbol": sh.ticker,
            "ts": sh.created_at or datetime.now(timezone.utc),
            "features": _json_or_empty(sh.features),
            "component_signals": _json_or_empty(comp),
            "outcome": sh.outcome,
            "embedding": _vector_literal(vec),
        })
        inserted += 1
    return inserted


def _json_or_empty(obj) -> str:
    import json
    return json.dumps(obj or {})


def _vector_literal(vec: np.ndarray) -> str:
    parts = ",".join(f"{float(x):.6f}" for x in vec[:EMBEDDING_DIM])
    return f"[{parts}]"


async def run(asset_class: str | None, limit: int) -> int:
    async with AsyncSessionLocal() as session:
        n = await embed_unlabeled(session, asset_class=asset_class, limit=limit)
        await session.commit()
        logger.info("embedded %d signal_history rows", n)
        return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asset-class", default=None, help="Filter by asset class (default: all)")
    parser.add_argument("--limit", type=int, default=1000, help="Max rows per run")
    args = parser.parse_args()
    asyncio.run(run(args.asset_class, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
