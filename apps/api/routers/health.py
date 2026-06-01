from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from cache.redis import redis_ping
from cache.worker_status import read_heartbeats
from config import settings
from db.connection import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/ready")
async def ready():
    errors: list[str] = []

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        errors.append(f"db: {exc}")

    if not await redis_ping():
        errors.append("redis: ping failed")

    if errors:
        return {"status": "degraded", "errors": errors}
    return {"status": "ok"}


@router.get("/health/worker")
async def worker_health():
    """Liveness for the (HTTP-less) worker, derived from the Redis heartbeats it
    writes each tick. A heartbeat is 'stale' once older than 2x its asset class's
    tick cadence. Overall status is ok only if every heartbeat is fresh + ok."""
    heartbeats = await read_heartbeats()
    if not heartbeats:
        return {"status": "unknown", "detail": "no worker heartbeats found", "workers": {}}

    now = datetime.now(timezone.utc)
    cadence = {
        "crypto": settings.worker_tick_seconds_crypto,
        "equity": settings.worker_tick_seconds_equity,
        "option": settings.worker_tick_seconds_option,
        "forex": settings.worker_tick_seconds_forex,
    }
    workers: dict[str, dict] = {}
    overall_ok = True
    for asset_class, hb in heartbeats.items():
        try:
            age = (now - datetime.fromisoformat(hb["ts"])).total_seconds()
        except Exception:
            age = None
        max_age = cadence.get(asset_class, 900) * 2
        stale = age is None or age > max_age
        # A paused class is intentionally idle — fresh + paused is healthy, not degraded.
        paused = hb.get("status") == "paused"
        healthy = (hb.get("status") in ("ok", "paused")) and not stale
        overall_ok = overall_ok and healthy
        workers[asset_class] = {
            **hb,
            "age_seconds": round(age, 1) if age is not None else None,
            "stale": stale,
            "paused": paused,
            "healthy": healthy,
        }

    return {"status": "ok" if overall_ok else "degraded", "workers": workers}
