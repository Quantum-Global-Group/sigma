"""Tests for worker liveness (heartbeat + singleton lock) and /health/worker.

Redis is faked with an in-memory async stub so these run offline.
"""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

import cache.worker_status as ws


class _FakeRedis:
    """Minimal async Redis supporting get/set(nx,ex)/scan_iter for these tests."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def scan_iter(self, match=None):
        prefix = (match or "").rstrip("*")
        for k in list(self.store):
            if k.startswith(prefix):
                yield k

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


@pytest.fixture
def fake_redis(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(ws, "get_redis", lambda: r)
    # cache_get/cache_set in cache.redis also call get_redis there; point them
    # at our fake by patching the names worker_status imported.
    import json

    async def _cache_set(key, value, ttl):
        r.store[key] = json.dumps(value)

    async def _cache_get(key):
        v = r.store.get(key)
        return json.loads(v) if v is not None else None

    monkeypatch.setattr(ws, "cache_set", _cache_set)
    monkeypatch.setattr(ws, "cache_get", _cache_get)
    return r


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------

def test_write_then_read_heartbeat(fake_redis):
    async def go():
        await ws.write_heartbeat("equity", duration_s=1.2, status="ok", signals=5)
        hb = await ws.read_heartbeats()
        return hb
    hb = asyncio.run(go())
    assert "equity" in hb
    assert hb["equity"]["status"] == "ok"
    assert hb["equity"]["signals"] == 5


def test_read_heartbeats_empty(fake_redis):
    assert asyncio.run(ws.read_heartbeats()) == {}


def test_write_heartbeat_swallows_errors(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("redis down")
    monkeypatch.setattr(ws, "cache_set", boom)
    # must not raise
    asyncio.run(ws.write_heartbeat("equity", duration_s=0.1, status="ok"))


# ---------------------------------------------------------------------------
# singleton lock
# ---------------------------------------------------------------------------

def test_acquire_singleton_first_wins(fake_redis):
    async def go():
        a = await ws.acquire_singleton("inst-A", ttl=60)
        b = await ws.acquire_singleton("inst-B", ttl=60)
        return a, b
    a, b = asyncio.run(go())
    assert a is True
    assert b is False  # B can't take A's lock


def test_acquire_singleton_reclaim_same_instance(fake_redis):
    async def go():
        await ws.acquire_singleton("inst-A", ttl=60)
        return await ws.acquire_singleton("inst-A", ttl=60)
    assert asyncio.run(go()) is True  # our own restart re-claims


def test_refresh_singleton_holds_and_loses(fake_redis):
    async def go():
        await ws.acquire_singleton("inst-A", ttl=60)
        held = await ws.refresh_singleton("inst-A", ttl=60)
        lost = await ws.refresh_singleton("inst-B", ttl=60)
        return held, lost
    held, lost = asyncio.run(go())
    assert held is True
    assert lost is False  # B sees A owns it


def test_acquire_singleton_redis_down_proceeds(monkeypatch):
    def boom():
        raise RuntimeError("no redis")
    monkeypatch.setattr(ws, "get_redis", boom)
    # Redis unavailable must not block startup (fly enforces single instance).
    assert asyncio.run(ws.acquire_singleton("inst-A", ttl=60)) is True


# ---------------------------------------------------------------------------
# pause flag
# ---------------------------------------------------------------------------

def test_pause_then_resume(fake_redis):
    async def go():
        before = await ws.is_paused("forex")
        await ws.set_pause("forex", True, reason="NFP")
        during = await ws.is_paused("forex")
        pauses = await ws.read_pauses()
        await ws.set_pause("forex", False)
        after = await ws.is_paused("forex")
        return before, during, pauses, after
    before, during, pauses, after = asyncio.run(go())
    assert before is False
    assert during is True
    assert pauses["forex"]["reason"] == "NFP"
    assert after is False


def test_is_paused_defaults_false_on_redis_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("redis down")
    monkeypatch.setattr(ws, "cache_get", boom)
    # A cache outage must never silently halt trading.
    assert asyncio.run(ws.is_paused("forex")) is False


def test_only_paused_classes_appear(fake_redis):
    async def go():
        await ws.set_pause("forex", True)
        return await ws.read_pauses()
    pauses = asyncio.run(go())
    assert set(pauses) == {"forex"}


# ---------------------------------------------------------------------------
# GET /health/worker
# ---------------------------------------------------------------------------

def _hb(asset_class, status="ok", age_s=10.0):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    return {"asset_class": asset_class, "ts": ts, "duration_s": 1.0,
            "status": status, "error": None, "signals": 3}


def test_worker_health_unknown_when_no_heartbeats(monkeypatch):
    import routers.health as h
    async def _none():
        return {}
    monkeypatch.setattr(h, "read_heartbeats", _none)
    out = asyncio.run(h.worker_health())
    assert out["status"] == "unknown"


def test_worker_health_ok_when_fresh(monkeypatch):
    import routers.health as h
    async def _hbs():
        return {"equity": _hb("equity", "ok", age_s=10.0)}
    monkeypatch.setattr(h, "read_heartbeats", _hbs)
    out = asyncio.run(h.worker_health())
    assert out["status"] == "ok"
    assert out["workers"]["equity"]["healthy"] is True
    assert out["workers"]["equity"]["stale"] is False


def test_worker_health_degraded_when_stale(monkeypatch):
    import routers.health as h
    async def _hbs():
        return {"equity": _hb("equity", "ok", age_s=5000.0)}
    monkeypatch.setattr(h, "read_heartbeats", _hbs)
    out = asyncio.run(h.worker_health())
    assert out["status"] == "degraded"
    assert out["workers"]["equity"]["stale"] is True


def test_worker_health_degraded_when_last_tick_errored(monkeypatch):
    import routers.health as h
    async def _hbs():
        return {"equity": _hb("equity", "error", age_s=10.0)}
    monkeypatch.setattr(h, "read_heartbeats", _hbs)
    out = asyncio.run(h.worker_health())
    assert out["status"] == "degraded"
    assert out["workers"]["equity"]["healthy"] is False


def test_worker_health_paused_is_healthy_not_degraded(monkeypatch):
    import routers.health as h
    async def _hbs():
        return {"forex": _hb("forex", "paused", age_s=10.0)}
    monkeypatch.setattr(h, "read_heartbeats", _hbs)
    out = asyncio.run(h.worker_health())
    assert out["status"] == "ok"                       # paused ≠ degraded
    assert out["workers"]["forex"]["paused"] is True
    assert out["workers"]["forex"]["healthy"] is True
