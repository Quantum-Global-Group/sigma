#!/usr/bin/env python
"""Fit + persist learned strategy weights from labeled signal_history (Phase C).

Computes each strategy's directional edge on labeled signals and writes
{model_dir}/strategy_weights_{asset_class}.json, which build_default_combiner
loads. Normally run nightly by the worker scheduler; this CLI is for an
immediate fit / debugging.

Usage:
    cd apps/api
    PYTHONPATH=. .venv/bin/python scripts/fit_strategy_weights.py [--asset-class forex]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import AsyncSessionLocal  # noqa: E402
from ml.strategy_weights import fit_and_store  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def _run(asset_classes: list[str]) -> None:
    async with AsyncSessionLocal() as session:
        for ac in asset_classes:
            weights = await fit_and_store(session, ac)
            print(f"{ac}: {weights if weights else 'no edge — equal weights kept'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-class", action="append", dest="asset_classes",
                        help="Repeatable; defaults to crypto,equity,forex")
    args = parser.parse_args()
    asyncio.run(_run(args.asset_classes or ["crypto", "equity", "forex"]))


if __name__ == "__main__":
    main()
