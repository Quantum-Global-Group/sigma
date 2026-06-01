"""Execution pause/resume + forex run_cycle tests (PR-J).

The shared `client` fixture authenticates as a non-internal user, so the
internal-gated endpoints return 403 — exactly the guard we want to verify
without wiring a real worker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def test_pause_requires_internal_secret(client, auth_headers):
    r = client.post("/execution/pause", headers=auth_headers, json={"asset_class": "forex"})
    assert r.status_code == 403
    assert "internal" in r.json()["detail"].lower()


def test_resume_requires_internal_secret(client, auth_headers):
    r = client.post("/execution/resume", headers=auth_headers, json={"asset_class": "forex"})
    assert r.status_code == 403


def test_pause_rejects_unknown_asset_class(client, auth_headers):
    r = client.post("/execution/pause", headers=auth_headers, json={"asset_class": "bogus"})
    assert r.status_code == 422   # pattern-constrained


def test_run_cycle_accepts_forex_pattern(client, auth_headers):
    # forex must be a valid asset_class now (was missing from the pattern).
    # Non-internal → 403 (not 422), proving the pattern accepts "forex".
    r = client.post("/execution/run_cycle", headers=auth_headers, json={"asset_class": "forex"})
    assert r.status_code == 403


def test_execution_status_reports_forex_cadence_and_pauses(client, auth_headers):
    with patch("routers.execution.read_pauses", new=AsyncMock(return_value={"forex": {"paused": True}})):
        r = client.get("/execution/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "worker_asset_classes_default_forex_seconds" in body
    assert body["paused"] == ["forex"]
