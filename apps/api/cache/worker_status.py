"""Worker liveness + singleton coordination via Redis.

Shared by apps/worker (writes heartbeats, holds the singleton lock) and
apps/api (reads heartbeats for GET /health/worker). All functions degrade
gracefully when Redis is unreachable — observability must never crash the
trading loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .redis import cache_get, cache_set, get_redis

logger = logging.getLogger(__name__)

HEARTBEAT_PREFIX = "worker:heartbeat:"
LOCK_KEY = "worker:singleton"
PAUSE_PREFIX = "worker:pause:"
OPEND_STATUS_KEY = "worker:opend"
MT5_BRIDGE_STATUS_KEY = "worker:mt5_bridge"
_PAUSE_TTL = 30 * 24 * 3600   # 30 days — effectively persistent, self-cleaning


async def write_opend_status(reachable: bool, detail: str, ttl: int = 1800) -> None:
    """Record the latest OpenD reachability probe. Best-effort — never raises."""
    payload = {
        "reachable": reachable,
        "detail": detail,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await cache_set(OPEND_STATUS_KEY, payload, ttl=ttl)
    except Exception:
        logger.warning("opend status write failed", exc_info=True)


async def read_opend_status() -> Optional[dict]:
    """Return the last OpenD status payload, or None if never written / Redis down."""
    try:
        return await cache_get(OPEND_STATUS_KEY)
    except Exception:
        logger.warning("opend status read failed", exc_info=True)
        return None


async def write_mt5_bridge_status(reachable: bool, detail: str, ttl: int = 1800) -> None:
    """Record the latest MT5 bridge reachability probe. Best-effort."""
    payload = {
        "reachable": reachable,
        "detail": detail,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await cache_set(MT5_BRIDGE_STATUS_KEY, payload, ttl=ttl)
    except Exception:
        logger.warning("mt5 bridge status write failed", exc_info=True)


async def read_mt5_bridge_status() -> Optional[dict]:
    """Return the last MT5 bridge status payload, or None if never written."""
    try:
        return await cache_get(MT5_BRIDGE_STATUS_KEY)
    except Exception:
        logger.warning("mt5 bridge status read failed", exc_info=True)
        return None


def _heartbeat_key(asset_class: str) -> str:
    return f"{HEARTBEAT_PREFIX}{asset_class}"


def _pause_key(asset_class: str) -> str:
    return f"{PAUSE_PREFIX}{asset_class}"


async def set_pause(asset_class: str, paused: bool, reason: Optional[str] = None) -> None:
    """Pause/resume one asset class without redeploying. The worker checks this
    each loop iteration. No TTL — the flag persists until explicitly resumed."""
    try:
        r = get_redis()
        key = _pause_key(asset_class)
        if paused:
            await cache_set(key, {"paused": True, "reason": reason,
                                  "ts": datetime.now(timezone.utc).isoformat()}, _PAUSE_TTL)
        else:
            await r.delete(key)
    except Exception:
        logger.warning("set_pause failed for %s", asset_class, exc_info=True)


async def is_paused(asset_class: str) -> bool:
    """Whether `asset_class` is paused. Defaults to False on any Redis error so a
    cache outage never silently halts trading."""
    try:
        return bool(await cache_get(_pause_key(asset_class)))
    except Exception:
        logger.warning("is_paused check failed for %s — assuming not paused", asset_class, exc_info=True)
        return False


async def read_pauses() -> dict[str, dict]:
    """Return {asset_class: pause_payload} for every paused asset class."""
    out: dict[str, dict] = {}
    try:
        r = get_redis()
        async for key in r.scan_iter(match=f"{PAUSE_PREFIX}*"):
            payload = await cache_get(key)
            if payload:
                ac = key.replace(PAUSE_PREFIX, "")
                out[ac] = payload
    except Exception:
        logger.warning("read_pauses failed", exc_info=True)
    return out


async def write_heartbeat(
    asset_class: str,
    *,
    duration_s: float,
    status: str,
    error: Optional[str] = None,
    signals: Optional[int] = None,
    ttl: int = 3600,
) -> None:
    """Record the outcome of one tick. Best-effort — never raises."""
    payload = {
        "asset_class": asset_class,
        "ts": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(float(duration_s), 3),
        "status": status,            # "ok" | "error"
        "error": error,
        "signals": signals,
    }
    try:
        await cache_set(_heartbeat_key(asset_class), payload, ttl=ttl)
    except Exception:
        logger.warning("heartbeat write failed for %s", asset_class, exc_info=True)


async def read_heartbeats() -> dict[str, dict]:
    """Return {asset_class: heartbeat} for every live worker heartbeat key."""
    out: dict[str, dict] = {}
    try:
        r = get_redis()
        async for key in r.scan_iter(match=f"{HEARTBEAT_PREFIX}*"):
            hb = await cache_get(key)
            if hb:
                out[hb.get("asset_class", key.replace(HEARTBEAT_PREFIX, ""))] = hb
    except Exception:
        logger.warning("heartbeat read failed", exc_info=True)
    return out


async def acquire_singleton(instance_id: str, ttl: int) -> bool:
    """Claim the worker singleton lock. True if we hold it (incl. our own
    restart re-claim), False if another live instance holds it."""
    try:
        r = get_redis()
        if await r.set(LOCK_KEY, instance_id, nx=True, ex=ttl):
            return True
        current = await r.get(LOCK_KEY)
        return current == instance_id
    except Exception:
        # Redis down: don't block startup. fly.toml already enforces a single
        # machine; the lock is belt-and-suspenders.
        logger.warning("singleton acquire failed (Redis?) — proceeding", exc_info=True)
        return True


async def refresh_singleton(instance_id: str, ttl: int) -> bool:
    """Extend our lock TTL. Returns False if another instance has taken it
    (caller should shut down). Redis errors are treated as 'keep running'."""
    try:
        r = get_redis()
        current = await r.get(LOCK_KEY)
        if current in (None, instance_id):
            await r.set(LOCK_KEY, instance_id, ex=ttl)
            return True
        logger.error("singleton lock held by %s, not us (%s) — yielding", current, instance_id)
        return False
    except Exception:
        logger.warning("singleton refresh failed (Redis?) — proceeding", exc_info=True)
        return True


async def release_singleton(instance_id: str) -> None:
    """Release the singleton lock on graceful shutdown so the next worker can
    start immediately (no waiting out the TTL). Best-effort: only deletes the
    lock when it's still ours, so we never steal it from a successor; Redis
    errors are swallowed."""
    try:
        r = get_redis()
        current = await r.get(LOCK_KEY)
        if current in (None, instance_id):
            await r.delete(LOCK_KEY)
            logger.info("singleton lock released (%s)", instance_id)
    except Exception:
        logger.warning("singleton release failed (Redis?)", exc_info=True)
