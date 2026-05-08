"""Smoke tests for the new positions / orders / execution routers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_run_cycle_rejects_non_internal_callers(client, auth_headers):
    resp = client.post(
        "/execution/run_cycle",
        json={"asset_class": "crypto"},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    assert "X-Internal-Secret" in resp.json()["detail"]


def test_execution_status_returns_config(client, auth_headers):
    resp = client.get("/execution/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["executor_mode"] in ("paper", "coinbase")
    assert isinstance(data["coinbase_sandbox"], bool)


def test_positions_endpoint_returns_list(client, auth_headers):
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    fake_session.commit = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_session)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("routers.positions.select"), \
         patch("db.connection.AsyncSessionLocal", return_value=cm):
        resp = client.get("/positions?asset_class=crypto", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_orders_endpoint_returns_list(client, auth_headers):
    with patch("routers.orders.select"):
        resp = client.get("/orders?limit=10", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []
