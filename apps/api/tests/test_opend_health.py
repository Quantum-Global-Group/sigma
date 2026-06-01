"""OpenD supervision tests (PR-L) — reachability probe, Redis status, health,
and the worker's _supervise_opend gate."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from markets.opend_health import check_opend


# ---------------------------------------------------------------------------
# check_opend (injected connector — no real socket)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_opend_reachable():
    async def ok(host, port, timeout):
        return None
    reachable, detail = await check_opend("127.0.0.1", 11111, connector=ok)
    assert reachable is True
    assert "11111" in detail


@pytest.mark.asyncio
async def test_check_opend_refused():
    async def refused(host, port, timeout):
        raise ConnectionRefusedError("connection refused")
    reachable, detail = await check_opend("127.0.0.1", 11111, connector=refused)
    assert reachable is False
    assert "ConnectionRefusedError" in detail


@pytest.mark.asyncio
async def test_check_opend_timeout():
    async def slow(host, port, timeout):
        raise asyncio.TimeoutError()
    reachable, detail = await check_opend("127.0.0.1", 11111, connector=slow)
    assert reachable is False
    assert "timeout" in detail.lower()


# ---------------------------------------------------------------------------
# Redis status round-trip (reuses the fake_redis fixture from test_worker_status)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_opend_status_roundtrip(monkeypatch):
    import cache.worker_status as ws
    import json

    class _FakeRedis:
        def __init__(self):
            self.store = {}

    r = _FakeRedis()
    monkeypatch.setattr(ws, "get_redis", lambda: r)

    async def _set(key, value, ttl):
        r.store[key] = json.dumps(value)

    async def _get(key):
        v = r.store.get(key)
        return json.loads(v) if v is not None else None

    monkeypatch.setattr(ws, "cache_set", _set)
    monkeypatch.setattr(ws, "cache_get", _get)

    assert await ws.read_opend_status() is None
    await ws.write_opend_status(False, "timeout connecting")
    status = await ws.read_opend_status()
    assert status["reachable"] is False
    assert "timeout" in status["detail"]


# ---------------------------------------------------------------------------
# /health/worker surfaces OpenD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_surfaces_opend(monkeypatch):
    import routers.health as h

    async def _hbs():
        return {}
    async def _opend():
        return {"reachable": False, "detail": "down", "ts": "2026-06-01T00:00:00+00:00"}

    monkeypatch.setattr(h, "read_heartbeats", _hbs)
    monkeypatch.setattr(h, "read_opend_status", _opend)
    out = await h.worker_health()
    assert out["opend"]["reachable"] is False


# ---------------------------------------------------------------------------
# worker _supervise_opend gate
# ---------------------------------------------------------------------------

_worker = Path(__file__).parents[2] / "worker"
if str(_worker) not in sys.path:
    sys.path.insert(0, str(_worker))


@pytest.mark.asyncio
async def test_supervise_opend_true_when_reachable(monkeypatch):
    import options_tick as ot
    monkeypatch.setattr("markets.opend_health.check_opend",
                        lambda *a, **k: _coro((True, "ok")))
    monkeypatch.setattr("cache.worker_status.write_opend_status",
                        lambda *a, **k: _coro(None))
    assert await ot._supervise_opend() is True


@pytest.mark.asyncio
async def test_supervise_opend_false_when_down_no_restart(monkeypatch):
    import options_tick as ot
    monkeypatch.setattr("markets.opend_health.check_opend",
                        lambda *a, **k: _coro((False, "refused")))
    monkeypatch.setattr("cache.worker_status.write_opend_status",
                        lambda *a, **k: _coro(None))
    monkeypatch.setattr("config.settings.opend_restart_command", "")
    assert await ot._supervise_opend() is False


def _coro(value):
    async def _c():
        return value
    return _c()
