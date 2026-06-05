"""P&L + forex-visibility router tests (PR-G) — uses the shared client fixture.

The conftest `client` fixture authenticates and returns a no-op DB (empty
results), so these assert routing/validation + empty-state shapes.
"""

from __future__ import annotations


def test_portfolio_pnl_empty(client, auth_headers):
    r = client.get("/portfolio/pnl", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_realized"] == 0 and body["total_unrealized"] == 0
    assert body["open_positions"] == 0
    assert "base_equity" in body and "total_value" in body
    assert body["total_value"] == body["base_equity"]   # no positions → value == base


def test_equity_curve_empty(client, auth_headers):
    r = client.get("/portfolio/equity-curve?days=30", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_equity_curve_days_validation(client, auth_headers):
    assert client.get("/portfolio/equity-curve?days=0", headers=auth_headers).status_code == 422
    assert client.get("/portfolio/equity-curve?days=999", headers=auth_headers).status_code == 422


def test_positions_accepts_forex(client, auth_headers):
    r = client.get("/positions?asset_class=forex", headers=auth_headers)
    assert r.status_code == 200          # was 422 before the pattern widened


def test_orders_accepts_forex_and_option(client, auth_headers):
    assert client.get("/orders?asset_class=forex", headers=auth_headers).status_code == 200
    assert client.get("/orders?asset_class=option", headers=auth_headers).status_code == 200


def test_orders_rejects_unknown_asset_class(client, auth_headers):
    assert client.get("/orders?asset_class=bogus", headers=auth_headers).status_code == 422
