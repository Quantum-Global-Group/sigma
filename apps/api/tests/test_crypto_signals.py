"""Crypto-asset-class regression tests for /signals.

Equity remains the default; these confirm that an explicit `asset_class=crypto`
flows through the pipeline and reaches the request payload."""

from unittest.mock import AsyncMock, patch

import pytest

from ml.inference import SignalResult


MOCK_SIGNAL = SignalResult("BUY", 0.6789, 0.0123, {"model": 0.5, "sentiment": 0.2, "regime": 0.3})
MOCK_SIGNAL.model_version = "v1.0"


@pytest.fixture
def mock_pipeline():
    with patch("routers.signals.run_signal_pipeline", return_value=MOCK_SIGNAL) as p:
        yield p


@pytest.fixture
def mock_rate_limit():
    with patch("routers.signals.check_rate_limit", new_callable=AsyncMock):
        yield


def test_crypto_signal_routes_through_pipeline(client, mock_cache_miss, mock_pipeline, mock_rate_limit, auth_headers):
    resp = client.post(
        "/signals",
        json={"ticker": "BTC-USD", "timeframe": "5m", "asset_class": "crypto"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ticker"] == "BTC-USD"
    assert data["timeframe"] == "5m"
    assert data["asset_class"] == "crypto"
    assert data["component_weights"] == {"model": 0.5, "sentiment": 0.2, "regime": 0.3}

    # Pipeline received asset_class=crypto
    _, kwargs = mock_pipeline.call_args
    assert kwargs.get("asset_class") == "crypto"


def test_equity_default_asset_class(client, mock_cache_miss, mock_pipeline, mock_rate_limit, auth_headers):
    resp = client.post(
        "/signals",
        json={"ticker": "AAPL", "timeframe": "daily"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["asset_class"] == "equity"


def test_unknown_asset_class_rejected(client, mock_rate_limit, auth_headers):
    resp = client.post(
        "/signals",
        json={"ticker": "AAPL", "asset_class": "options"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
