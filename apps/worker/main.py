"""Live trading loop entry point.

Runs a per-asset-class cycle on a fixed cadence (the full body lives in
worker.tick.tick_once):
    1. Universe selection
    2. Per-symbol: candle fetch → features → strategy combiner (blended with the
       trained registry model) → SignalResult
    3. Risk-scaled position sizing against the live account equity
    4. Execution (paper | coinbase | alpaca) → persist orders/positions/exit state

This module owns the loop: asset-class fan-out, fixed-cadence scheduling, and
graceful SIGINT/SIGTERM shutdown. Single instance only — two workers would
race on positions and double-place orders."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
import time
from typing import Iterable

# Ensure apps/api is on sys.path when running as a separate service container.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api")))

from config import settings  # noqa: E402
from cache.worker_status import (  # noqa: E402
    acquire_singleton,
    is_paused,
    refresh_singleton,
    release_singleton,
    write_heartbeat,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")


async def _run_tick(asset_class: str) -> None:
    """One pass over the configured universe for `asset_class`.

    Options use a chain-based cycle (options_tick_once); equity/crypto use the
    OHLCV-based tick_once. Exceptions propagate to the caller (_drive)."""
    if asset_class == "option":
        from worker.options_tick import options_tick_once as _opt_tick
        await _opt_tick()
    elif asset_class == "allocation":
        # The deployable strategy: monthly trend-filtered diversified rebalance
        # (docs/MODELS.md). Self-guards to act once per month.
        from worker.allocation_tick import allocation_rebalance
        await allocation_rebalance()
    else:
        from worker.tick import tick_once as _tick
        await _tick(asset_class)


def _interval_for(asset_class: str) -> int:
    if asset_class == "crypto":
        return settings.worker_tick_seconds_crypto
    if asset_class == "option":
        return settings.worker_tick_seconds_option
    if asset_class == "forex":
        return settings.worker_tick_seconds_forex
    if asset_class == "allocation":
        return settings.worker_tick_seconds_allocation
    return settings.worker_tick_seconds_equity


async def run_loop(asset_classes: Iterable[str], stop: asyncio.Event) -> None:
    asset_classes = list(asset_classes)
    instance_id = f"{socket.gethostname()}:{os.getpid()}"
    lock_ttl = max((_interval_for(ac) for ac in asset_classes), default=900) * 3

    # Singleton guard (belt-and-suspenders over fly.toml's single-instance
    # config): two workers would race on positions and double-place orders.
    if not await acquire_singleton(instance_id, lock_ttl):
        logger.error("another worker holds the singleton lock — exiting")
        return
    logger.info("singleton lock acquired (%s)", instance_id)

    # Reconcile the persisted book before the first tick: heal missing exit_state
    # rows + flat-but-open positions, and surface any broker divergences. Never
    # fatal — a failed reconcile logs (and reaches Sentry) but trading proceeds,
    # since each tick reloads state from the DB anyway.
    try:
        from worker.reconcile import reconcile_startup
        reconcile_summary = await reconcile_startup(asset_classes)
        reconcile_summary.log(logger)
    except Exception:
        logger.exception("startup reconciliation failed — proceeding to trade loop")

    # Self-evolution background jobs run only on the singleton holder, so they
    # never double-run across instances. Optional + best-effort: a scheduler
    # failure must never take down the trading loop.
    scheduler = _maybe_start_scheduler(asset_classes)

    async def _drive(ac: str) -> None:
        interval = _interval_for(ac)
        while not stop.is_set():
            t0 = time.monotonic()
            err: str | None = None

            # Per-asset-class pause: skip the tick (but keep looping) so an
            # operator can halt one venue via POST /execution/pause and resume
            # it later without a redeploy.
            if await is_paused(ac):
                logger.info("[%s] paused — skipping tick", ac)
                await write_heartbeat(ac, duration_s=0.0, status="paused", ttl=interval * 4)
            else:
                try:
                    await _run_tick(ac)
                except Exception as exc:
                    err = f"{type(exc).__name__}: {exc}"
                    logger.exception("[%s] tick raised", ac)

                await write_heartbeat(
                    ac,
                    duration_s=time.monotonic() - t0,
                    status="error" if err else "ok",
                    error=err,
                    ttl=interval * 4,
                )
            if not await refresh_singleton(instance_id, lock_ttl):
                logger.error("lost singleton lock — stopping worker")
                stop.set()
                break

            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    try:
        await asyncio.gather(*(_drive(ac) for ac in asset_classes))
    finally:
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                logger.warning("scheduler shutdown failed", exc_info=True)
        # Release the singleton lock so the next worker can start immediately
        # (rather than waiting out the lock TTL).
        try:
            await release_singleton(instance_id)
        except Exception:
            logger.warning("singleton release failed", exc_info=True)


def _maybe_start_scheduler(asset_classes: list[str]):
    """Start the worker-internal self-evolution scheduler, or return None.

    Disabled via WORKER_SCHEDULER_ENABLED=false, and degrades to None if
    APScheduler isn't installed — the trading loop runs regardless."""
    if not settings.worker_scheduler_enabled:
        logger.info("worker scheduler disabled (WORKER_SCHEDULER_ENABLED=false)")
        return None
    try:
        from worker.scheduler import build_scheduler
        scheduler = build_scheduler(asset_classes)
        scheduler.start()
        logger.info("self-evolution scheduler started")
        return scheduler
    except Exception:
        logger.warning("could not start self-evolution scheduler — continuing without it", exc_info=True)
        return None


def _parse_asset_classes() -> list[str]:
    raw = os.getenv("WORKER_ASSET_CLASSES", "crypto")
    return [ac.strip() for ac in raw.split(",") if ac.strip()]


def _init_sentry() -> None:
    """Capture worker-loop exceptions in Sentry (mirrors apps/api/main.py).

    Without this the worker fails silently — a dead trading loop produces no
    alert. No-op when SENTRY_DSN is unset (local/dev)."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.2,
        )
        logger.info("Sentry initialized for worker (env=%s)", settings.environment)
    except Exception:
        logger.warning("Sentry init failed — continuing without it", exc_info=True)


def _maybe_install_synthetic() -> None:
    """Offline full-run: swap in synthetic market data so every asset class trades
    without network/creds (forex keeps real OANDA when a token is set)."""
    if not settings.synthetic_data:
        return
    try:
        from sim.synthetic import install_synthetic_providers
        installed = install_synthetic_providers()
        logger.warning("SYNTHETIC_DATA on — synthetic providers for %s", installed)
    except Exception:
        logger.exception("failed to install synthetic providers")


def main() -> None:
    _init_sentry()
    _maybe_install_synthetic()
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
