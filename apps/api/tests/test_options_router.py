"""Tests for the options API router (Phase 6) — fully mocked, no live OpenD.

Uses the conftest.py TestClient fixture + the fake_db session override.
The chain-fetch path in /options/candidates is patched so OpenD is never
contacted (same pattern as test_moomoo_connector.py for the SDK).
"""

from __future__ import annotations

import sys
import types
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake moomoo SDK (keep CI independent of futu/moomoo install)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_moomoo(monkeypatch):
    m = types.ModuleType("moomoo")
    m.RET_OK = 0
    for cls in ("TrdEnv", "TrdSide", "OrderType", "KLType", "TrdMarket", "SecurityFirm"):
        setattr(m, cls, type(cls, (), {"BUY": "BUY", "SELL": "SELL", "SIMULATE": "SIMULATE",
                                       "REAL": "REAL", "MARKET": "MARKET", "NORMAL": "NORMAL",
                                       "K_DAY": "K_DAY", "US": "US", "FUTUINC": "FUTUINC"}))
    m.OpenQuoteContext = object
    m.OpenSecTradeContext = object
    monkeypatch.setitem(sys.modules, "moomoo", m)
    return m


# ---------------------------------------------------------------------------
# /options/positions
# ---------------------------------------------------------------------------

def test_options_positions_returns_empty_list(client, auth_headers):
    """Default fake_db has no rows → empty list."""
    resp = client.get("/options/positions", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_options_positions_open_only_default(client, auth_headers):
    """open_only defaults to True — endpoint must accept the request."""
    resp = client.get("/options/positions?open_only=true", headers=auth_headers)
    assert resp.status_code == 200


def test_options_positions_limit_validation(client, auth_headers):
    """limit=0 should fail validation (ge=1)."""
    resp = client.get("/options/positions?limit=0", headers=auth_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /options/exposure
# ---------------------------------------------------------------------------

def test_options_exposure_returns_zero_when_no_positions(client, auth_headers):
    resp = client.get("/options/exposure", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "net_greeks" in data
    assert data["net_greeks"]["delta"] == 0.0
    assert data["positions_count"] == 0
    assert data["greek_limits_ok"] is True
    assert data["greek_breaches"] == []


# ---------------------------------------------------------------------------
# /options/candidates
# ---------------------------------------------------------------------------

def test_options_candidates_requires_underlying(client, auth_headers):
    """underlying is a required query param."""
    resp = client.get("/options/candidates", headers=auth_headers)
    assert resp.status_code == 422


def test_options_candidates_bad_expiry_format(client, auth_headers):
    resp = client.get("/options/candidates?underlying=AAPL&expiry=not-a-date", headers=auth_headers)
    assert resp.status_code == 422


def test_options_candidates_returns_empty_when_opend_unavailable(client, auth_headers):
    """When MoomooOptionData raises, the endpoint returns [] (graceful degrade).
    The router lazy-imports MoomooOptionData inside the handler, so patch it in
    its source module (markets.options) where the class lives."""
    with patch("markets.options.MoomooOptionData") as mock_cls:
        # Also patch the router's local reference (it does 'from markets.options import')
        mock_instance = MagicMock()
        mock_instance.list_expiries.side_effect = ConnectionRefusedError("OpenD down")
        mock_cls.return_value = mock_instance
        with patch("routers.options._nearest_expiry", return_value=None):
            resp = client.get("/options/candidates?underlying=AAPL", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_options_candidates_returns_empty_when_chain_empty(client, auth_headers):
    """Empty chain from OpenD → empty candidate list, not an error."""
    import pandas as pd
    import numpy as np
    from datetime import timedelta

    expiry = date.today() + timedelta(days=30)
    n = 60
    closes = 100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0.0005, 0.01, n)))
    df = pd.DataFrame({
        "open": closes * 0.999, "high": closes * 1.005,
        "low": closes * 0.995, "close": closes, "volume": [1e6] * n,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))

    mock_opt = MagicMock()
    mock_opt.list_expiries.return_value = [expiry]
    mock_opt.get_chain.return_value = []   # empty chain → no quotes → []
    mock_opt.get_quotes.return_value = []

    mock_adapter = MagicMock()
    mock_adapter.fetch_ohlcv.return_value = df

    with patch("markets.options.MoomooOptionData", return_value=mock_opt), \
         patch("markets.get_market_adapter", return_value=mock_adapter), \
         patch("routers.options._nearest_expiry", return_value=expiry):
        resp = client.get("/options/candidates?underlying=AAPL", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Regression: existing router fixes
# ---------------------------------------------------------------------------

def test_positions_accepts_option_asset_class(client, auth_headers):
    """After the fix, asset_class=option is a valid query param."""
    resp = client.get("/positions?asset_class=option", headers=auth_headers)
    assert resp.status_code == 200


def test_execution_status_has_option_seconds(client, auth_headers):
    """ExecutionStatus now includes the option tick cadence."""
    resp = client.get("/execution/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "worker_asset_classes_default_option_seconds" in data
    assert isinstance(data["worker_asset_classes_default_option_seconds"], int)


def test_run_cycle_option_validates_and_rejects_non_internal(client, auth_headers):
    """asset_class=option is now accepted by the validator (not 422); still 403 for non-internal."""
    resp = client.post(
        "/execution/run_cycle",
        json={"asset_class": "option"},
        headers=auth_headers,
    )
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.json()}"
