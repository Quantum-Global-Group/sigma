"""Model-lifecycle router tests (PR-E) — uses the shared client fixture.

The conftest `client` fixture authenticates as a non-internal user with a no-op
DB, so GETs return empty lists and the approve/reject guard returns 403 (they
require the internal secret).
"""

from __future__ import annotations


def test_list_champions_empty(client, auth_headers):
    r = client.get("/models/champions", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_list_promotions_empty(client, auth_headers):
    r = client.get("/models/promotions?status=pending", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_list_evaluations_empty(client, auth_headers):
    r = client.get("/models/evaluations?asset_class=equity", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_approve_requires_internal_secret(client, auth_headers):
    r = client.post("/models/promotions/123e4567-e89b-12d3-a456-426614174000/approve",
                    headers=auth_headers)
    assert r.status_code == 403
    assert "internal" in r.json()["detail"].lower()


def test_reject_requires_internal_secret(client, auth_headers):
    r = client.post("/models/promotions/123e4567-e89b-12d3-a456-426614174000/reject",
                    headers=auth_headers)
    assert r.status_code == 403


def test_promotions_status_filter_validation(client, auth_headers):
    r = client.get("/models/promotions?status=bogus", headers=auth_headers)
    assert r.status_code == 422   # pattern-constrained query param
