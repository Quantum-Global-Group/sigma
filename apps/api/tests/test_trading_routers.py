"""Smoke tests for the new positions / orders / execution routers."""


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


def test_positions_endpoint_returns_empty_list(client, auth_headers):
    """Default fake_db.execute returns scalars().all() == []."""
    resp = client.get("/positions?asset_class=crypto", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_orders_endpoint_returns_empty_list(client, auth_headers):
    resp = client.get("/orders?limit=10", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_orders_endpoint_filters_validate(client, auth_headers):
    """The asset_class query param is constrained to equity|crypto."""
    resp = client.get("/orders?asset_class=options", headers=auth_headers)
    assert resp.status_code == 422
