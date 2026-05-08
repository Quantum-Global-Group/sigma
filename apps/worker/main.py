"""Live trading loop entry point.

Runs a per-asset-class cycle on a fixed cadence:
    1. Universe selection
    2. Per-symbol: candle fetch → features → signal
    3. Strategy combiner → risk-scaled sizing
    4. Execution (paper or coinbase) → persist orders/positions/exit state

The full body of step 3-4 lands when razorBill is subtree-imported and its
risk/sizing/exits modules are ported into apps/api/risk/. Until then this
module owns the loop scaffolding so deployment, scheduling, and graceful
shutdown can be tested end-to-end."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Iterable

# Ensure apps/api is on sys.path when running as a separate service container.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api")))

from config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")


async def tick_once(asset_class: str) -> None:
    """One pass over the configured universe for `asset_class`."""
    from markets import get_market_adapter
    from universe import get_universe_selector
    from ml.pipeline import run_signal_pipeline

    adapter = get_market_adapter(asset_class)
    if not adapter.is_market_open():
        logger.info("[%s] market closed — skipping tick", asset_class)
        return

    selector = get_universe_selector(asset_class)
    symbols = selector.select()
    logger.info("[%s] tick: %d symbols", asset_class, len(symbols))

    for symbol in symbols:
        try:
            # Pipeline currently runs sync; offload so a slow fetch doesn't
            # block the event loop for the whole universe.
            result = await asyncio.to_thread(
                run_signal_pipeline, symbol, _default_timeframe(asset_class), asset_class=asset_class
            )
            logger.info(
                "[%s] %s -> %s (conf=%.2f, ret=%+.4f)",
                asset_class, symbol, result.signal, result.confidence, result.predicted_return,
            )
            # TODO(razorBill port): pass result through strategy combiner +
            # risk manager + sizing + execution, then persist orders/positions.
        except Exception:
            logger.exception("[%s] tick failed for %s", asset_class, symbol)


def _default_timeframe(asset_class: str) -> str:
    return "5m" if asset_class == "crypto" else "daily"


def _interval_for(asset_class: str) -> int:
    if asset_class == "crypto":
        return settings.worker_tick_seconds_crypto
    return settings.worker_tick_seconds_equity


async def run_loop(asset_classes: Iterable[str], stop: asyncio.Event) -> None:
    async def _drive(ac: str) -> None:
        interval = _interval_for(ac)
        while not stop.is_set():
            try:
                await tick_once(ac)
            except Exception:
                logger.exception("[%s] tick raised", ac)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(*(_drive(ac) for ac in asset_classes))


def _parse_asset_classes() -> list[str]:
    raw = os.getenv("WORKER_ASSET_CLASSES", "crypto")
    return [ac.strip() for ac in raw.split(",") if ac.strip()]


def main() -> None:
    asset_classes = _parse_asset_classes()
    if not asset_classes:
        logger.error("WORKER_ASSET_CLASSES is empty — nothing to do")
        sys.exit(1)
    if not settings.internal_secret:
        logger.warning("INTERNAL_SECRET is empty — worker will run but its calls would not authenticate against the API gateway")

    logger.info("Worker starting: asset_classes=%s", asset_classes)
    stop = asyncio.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM
            pass

    try:
        loop.run_until_complete(run_loop(asset_classes, stop))
    finally:
        loop.close()
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
