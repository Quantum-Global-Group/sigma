#!/usr/bin/env python
"""
Evaluate a model version against its labeled signals + (optionally) propose it.

Usage:
    python scripts/evaluate_models.py --asset-class equity --version v1.0
    python scripts/evaluate_models.py --asset-class equity --version cand-20260601 --propose

Writes a model_evaluations row from the labeled signal_history for that version.
With --propose, files a pending model_promotions row if it beats the incumbent
(human still approves via POST /models/promotions/{id}/approve). Normally the
worker-internal scheduler does this; this CLI is for manual/cron runs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import AsyncSessionLocal
from ml.evaluation import evaluate_model
from ml.promotion import propose_promotion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_models")


async def _discover_version(session, asset_class: str, requested: str) -> str:
    """Return the best matching model_version from signal_history.

    EnsembleSignalModel stores 'ensemble_v1.0' but settings.model_version is
    'v1.0'. If the requested string has no labeled rows, look for any version
    in signal_history that contains the requested string as a substring, or
    just return the most common labeled version for this asset class."""
    from sqlalchemy import text
    r = await session.execute(text("""
        SELECT model_version, COUNT(*) as n
        FROM signal_history
        WHERE asset_class = :ac AND labeled_at IS NOT NULL
        GROUP BY model_version ORDER BY n DESC
    """), {"ac": asset_class})
    rows = r.fetchall()
    if not rows:
        return requested
    versions = [row[0] for row in rows]
    # Exact match first
    if requested in versions:
        return requested
    # Substring match (e.g. 'v1.0' inside 'ensemble_v1.0')
    for v in versions:
        if requested in v or v in requested:
            logger.info("Version %r not found; using %r (found in signal_history)", requested, v)
            return v
    # Fall back to the most common version
    logger.info("Version %r not found; falling back to %r (most labeled)", requested, versions[0])
    return versions[0]


async def _run(asset_class: str, version: str, model_type: str, propose: bool) -> None:
    async with AsyncSessionLocal() as session:
        resolved = await _discover_version(session, asset_class, version)
        ev = await evaluate_model(session, asset_class, resolved, model_type=model_type)
        logger.info("Evaluated %s %s: n=%d directional_accuracy=%s",
                    asset_class, resolved, ev.n_samples, ev.directional_accuracy)
        if propose:
            await session.flush()
            promo = await propose_promotion(session, asset_class, resolved, model_type=model_type)
            logger.info("Proposed promotion: %s", "yes (pending)" if promo else "no (gate not met)")
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-class", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--model-type", default="ensemble")
    parser.add_argument("--propose", action="store_true", help="Propose a promotion if it beats the incumbent")
    args = parser.parse_args()
    asyncio.run(_run(args.asset_class, args.version, args.model_type, args.propose))


if __name__ == "__main__":
    main()
