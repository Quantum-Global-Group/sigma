"""Train the crypto RankingModel on Coinbase historical candles.

Usage:
    cd apps/api
    python scripts/train_ranking.py                       # use CRYPTO_UNIVERSE
    python scripts/train_ranking.py --symbols BTC-USD,ETH-USD
    python scripts/train_ranking.py --timeframe hourly --version v1.1
    python scripts/train_ranking.py --dry-run             # fetch + label only

Saves the fitted artifact to:
    {settings.model_dir}/crypto_ranking_{version}.pkl

The registry (`apps/api/ml/models/registry.py`) picks this up automatically
on the next worker tick — no other wiring required."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

# Make sibling packages importable when run as a script: `python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from markets import get_market_adapter  # noqa: E402
from ml.models.ranking import RankingModel  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("train_ranking")


def _resolve_symbols(arg: str | None) -> list[str]:
    if arg:
        raw = arg
    else:
        raw = os.getenv(
            "CRYPTO_UNIVERSE",
            "BTC-USD,ETH-USD,SOL-USD,LINK-USD,AVAX-USD,DOGE-USD,MATIC-USD,ATOM-USD",
        )
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _fetch_one(adapter, symbol: str, timeframe: str) -> pd.DataFrame | None:
    try:
        df = adapter.fetch_ohlcv(symbol, timeframe).copy()
    except Exception as exc:
        logger.warning("skip %s: %s", symbol, exc)
        return None
    df["symbol"] = symbol
    return df


def _summarize(frames: list[pd.DataFrame]) -> str:
    total = sum(len(f) for f in frames)
    return f"{total} bars across {len(frames)} symbols"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbol list. Defaults to $CRYPTO_UNIVERSE.",
    )
    parser.add_argument(
        "--timeframe",
        default="5m",
        help="Coinbase candle granularity (1m / 5m / hourly / 4h / daily). Default: 5m.",
    )
    parser.add_argument(
        "--version",
        default=settings.model_version,
        help=f"Artifact version tag. Default: settings.model_version ({settings.model_version}).",
    )
    parser.add_argument(
        "--out-dir",
        default=settings.model_dir,
        help=f"Where to save. Default: settings.model_dir ({settings.model_dir}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + label only; skip the actual fit and save.",
    )
    args = parser.parse_args()

    symbols = _resolve_symbols(args.symbols)
    if not symbols:
        logger.error("no symbols resolved — set CRYPTO_UNIVERSE or pass --symbols")
        return 1

    logger.info("training on %d symbols, timeframe=%s, version=%s", len(symbols), args.timeframe, args.version)

    adapter = get_market_adapter("crypto")
    t0 = time.monotonic()
    frames: list[pd.DataFrame] = []
    for sym in symbols:
        df = _fetch_one(adapter, sym, args.timeframe)
        if df is not None and not df.empty:
            frames.append(df)
            logger.info("  %s: %d bars", sym, len(df))
    fetch_secs = time.monotonic() - t0

    if not frames:
        logger.error("no usable data — aborting")
        return 1
    logger.info("fetch complete: %s in %.1fs", _summarize(frames), fetch_secs)

    if args.dry_run:
        logger.info("--dry-run: skipping fit + save")
        return 0

    model = RankingModel()
    logger.info("fitting (backend=%s)…", model.backend)
    t0 = time.monotonic()
    model.fit_from_ohlcv(frames)
    fit_secs = time.monotonic() - t0
    logger.info("fit complete in %.1fs", fit_secs)

    if not model._trained:
        logger.error("model never reached fit() — frames may be too short for ranking_window=%d",
                     settings.ranking_window)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"crypto_ranking_{args.version}.pkl"
    model.save(str(out_path))
    logger.info("saved %s (%.1f KB)", out_path, out_path.stat().st_size / 1024)

    try:
        from ml.experiment import start_run
        card = {
            "asset_class": "crypto",
            "model_type": "ranking",
            "version": args.version,
            "symbols": symbols,
            "timeframe": args.timeframe,
            "backend": model.backend,
            "artifact": str(out_path),
        }
        with start_run(f"ranking-crypto-{args.version}",
                       tags={"asset_class": "crypto", "model_type": "ranking"}) as run:
            run.log_params(card)
            run.log_artifact(str(out_path))
    except Exception:
        logger.debug("MLflow logging skipped for ranking train", exc_info=True)

    logger.info("registry will load this on the next worker tick — no further wiring needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
