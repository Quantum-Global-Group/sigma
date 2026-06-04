#!/usr/bin/env python
"""Compare strategy signals across a ticker universe (MVP backtest-style CLI).

Runs each strategy in isolation on historical bars and prints a comparison table.
Does not place orders — useful for seeing how different strategies behave with
the same OHLCV data the worker trades on.

Usage:
    cd apps/api
    PYTHONPATH=. python scripts/compare_universe_strategies.py --asset-class equity
    PYTHONPATH=. python scripts/compare_universe_strategies.py --symbols AAPL MSFT --strategies momentum,ict,ml
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets import get_market_adapter
from ml.sequences import FeatureEngineer
from ml.strategies.combiner import _STRATEGY_FACTORIES, StrategyCombiner, combine_to_result

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("compare_universe")


def _default_symbols(asset_class: str) -> list[str]:
    if asset_class == "crypto":
        return [s.strip() for s in "BTC-USD,ETH-USD,SOL-USD".split(",")]
    if asset_class == "forex":
        return ["EUR_USD", "GBP_USD", "USD_JPY"]
    return ["AAPL", "MSFT", "GOOG"]


def _default_timeframe(asset_class: str) -> str:
    if asset_class == "crypto":
        return "5m"
    if asset_class == "forex":
        return "4h"
    return "daily"


def _build_combiner(names: list[str]) -> StrategyCombiner:
    strategies = {}
    weights = {}
    for name in names:
        factory = _STRATEGY_FACTORIES.get(name)
        if factory is None:
            logger.warning("unknown strategy %r — skipping", name)
            continue
        strategies[name] = factory()
        weights[name] = 1.0
    if not strategies:
        raise RuntimeError("no valid strategies selected")
    return StrategyCombiner(strategies, weights)


def _score_row(combined, px: float) -> dict:
    result = combine_to_result(combined)
    comp = (result.component_weights or {}).get("component_signals", {})
    return {
        "signal": result.signal,
        "strength": round(combined.strength, 4),
        "confidence": round(result.confidence, 4),
        "px": px,
        "components": comp,
    }


def compare(
    asset_class: str,
    symbols: list[str],
    strategy_names: list[str],
    timeframe: str,
) -> pd.DataFrame:
    adapter = get_market_adapter(asset_class)
    fe = FeatureEngineer()
    rows: list[dict] = []

    for symbol in symbols:
        try:
            df = adapter.fetch_ohlcv(symbol, timeframe)
        except Exception as exc:
            logger.warning("%s: fetch failed (%s)", symbol, exc)
            continue
        if df.empty or len(df) < 30:
            logger.warning("%s: insufficient bars", symbol)
            continue
        feats = fe.compute(df)
        px = float(feats["c"].iloc[-1])

        # Combined (all selected strategies)
        combiner = _build_combiner(strategy_names)
        combined = combiner.combine_signals(symbol, feats, px, model_predictions={})
        row = {"symbol": symbol, "mode": "combined", **_score_row(combined, px)}
        rows.append(row)

        # Each strategy in isolation
        for name in strategy_names:
            if name not in _STRATEGY_FACTORIES:
                continue
            solo = _build_combiner([name])
            sig = solo.combine_signals(symbol, feats, px, model_predictions={})
            rows.append({"symbol": symbol, "mode": name, **_score_row(sig, px)})

    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asset-class", default="equity", choices=["equity", "crypto", "forex"])
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--strategies", default="momentum,mean_reversion,ict,ml",
                        help="Comma-separated strategy names")
    parser.add_argument("--timeframe", default=None)
    args = parser.parse_args()

    symbols = args.symbols or _default_symbols(args.asset_class)
    timeframe = args.timeframe or _default_timeframe(args.asset_class)
    names = [s.strip() for s in args.strategies.split(",") if s.strip()]

    logger.info("Comparing %d symbols × %d strategies (%s, %s)", len(symbols), len(names), args.asset_class, timeframe)
    df = compare(args.asset_class, symbols, names, timeframe)
    if df.empty:
        logger.error("no results — check symbols and data providers")
        return 1

    cols = ["symbol", "mode", "signal", "strength", "confidence"]
    print(df[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
