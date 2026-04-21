from unittest.mock import AsyncMock, patch

import pytest

from ml.inference import SignalResult


MOCK_SIGNAL = SignalResult("BUY", 0.7234, 0.0187)
MOCK_SIGNAL.model_version = "v1.0"


@pytest.fixture
def mock_pipeline():
    with patch("routers.signals.run_signal_pipeline", return_value=MOCK_SIGNAL):
        yield


@pytest.fixture
def mock_rate_limit():
    with patch("routers.signals.check_rate_limit", new_callable=AsyncMock):
        yield


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "timestamp" in data


def test_signal_happy_path(client, mock_cache_miss, mock_pipeline, mock_rate_limit, auth_headers):
    resp = client.post(
        "/signals",
        json={"ticker": "AAPL", "timeframe": "daily"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["timeframe"] == "daily"
    assert data["signal"] in ("BUY", "SELL", "HOLD")
    assert 0.0 <= data["confidence"] <= 1.0
    assert isinstance(data["predicted_return"], float)
    assert "model_version" in data
    assert "timestamp" in data
    assert isinstance(data["cached"], bool)


def test_signal_cache_hit(client, mock_rate_limit, auth_headers):
    cached_payload = {
        "ticker": "AAPL",
        "timeframe": "daily",
        "signal": "BUY",
        "confidence": 0.85,
        "predicted_return": 0.02,
        "model_version": "v1.0",
        "timestamp": "2026-04-20T14:32:00+00:00",
        "cached": True,
    }
    with patch("routers.signals.cache_get", new_callable=AsyncMock, return_value=cached_payload):
        resp = client.post(
            "/signals",
            json={"ticker": "AAPL", "timeframe": "daily"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["cached"] is True


def test_signal_invalid_ticker(client, mock_cache_miss, mock_rate_limit, auth_headers):
    with patch("routers.signals.run_signal_pipeline", side_effect=ValueError("No data returned for ticker: XXXX")):
        resp = client.post(
            "/signals",
            json={"ticker": "XXXX", "timeframe": "daily"},
            headers=auth_headers,
        )
    assert resp.status_code == 422


def test_signal_no_auth():
    from fastapi.testclient import TestClient
    from main import app
    c = TestClient(app, raise_server_exceptions=False)
    resp = c.post("/signals", json={"ticker": "AAPL"})
    assert resp.status_code in (401, 422)


def test_signal_invalid_timeframe(client, mock_rate_limit, auth_headers):
    with patch("routers.signals.cache_get", new_callable=AsyncMock, return_value=None):
        resp = client.post(
            "/signals",
            json={"ticker": "AAPL", "timeframe": "weekly"},
            headers=auth_headers,
        )
    assert resp.status_code == 422
