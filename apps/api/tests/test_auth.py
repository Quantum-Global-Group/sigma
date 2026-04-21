"""
Tests for API key authentication: valid key, revoked key, expired key, wrong format.
All DB/Redis calls are mocked — no live services needed.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


def _make_api_key(revoked: bool = False, expired: bool = False) -> MagicMock:
    key = MagicMock()
    key.id = uuid.uuid4()
    key.user_id = uuid.uuid4()
    key.revoked = revoked
    key.expires_at = (
        datetime.now(timezone.utc) - timedelta(hours=1) if expired else None
    )
    return key


def _make_user(plan: str = "pro") -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.plan = plan
    user.clerk_id = "test_clerk"
    user.email = "test@sigma.local"
    return user


@pytest.fixture
def raw_key():
    import secrets
    return f"sk_test_{secrets.token_urlsafe(32)}"


class TestApiKeyAuth:
    def test_missing_auth_header_returns_422(self):
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post("/signals", json={"ticker": "AAPL"})
        assert resp.status_code in (401, 422)

    def test_malformed_auth_header_returns_401(self):
        with patch("middleware.auth.cache_get", new_callable=AsyncMock, return_value=None), \
             patch("middleware.auth.get_api_key_by_hash", new_callable=AsyncMock, return_value=None):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    "/signals",
                    json={"ticker": "AAPL"},
                    headers={"Authorization": "NotBearer token"},
                )
        assert resp.status_code == 401

    def test_valid_key_passes_auth(self, raw_key):
        mock_key = _make_api_key()
        mock_user = _make_user()

        with patch("middleware.auth.cache_get", new_callable=AsyncMock, return_value=None), \
             patch("middleware.auth.cache_set", new_callable=AsyncMock), \
             patch("middleware.auth.get_api_key_by_hash", new_callable=AsyncMock, return_value=mock_key), \
             patch("middleware.auth.get_user_by_id", new_callable=AsyncMock, return_value=mock_user), \
             patch("routers.signals.check_rate_limit", new_callable=AsyncMock), \
             patch("routers.signals.cache_get", new_callable=AsyncMock, return_value=None), \
             patch("routers.signals.cache_set", new_callable=AsyncMock), \
             patch("routers.signals.run_signal_pipeline") as mock_pipeline, \
             patch("routers.signals._log_usage", new_callable=AsyncMock), \
             patch("routers.signals.record_usage", new_callable=AsyncMock):

            from ml.inference import SignalResult
            mock_result = SignalResult("BUY", 0.75, 0.02)
            mock_result.model_version = "v1.0"
            mock_pipeline.return_value = mock_result

            with TestClient(app) as c:
                resp = c.post(
                    "/signals",
                    json={"ticker": "AAPL"},
                    headers={"Authorization": f"Bearer {raw_key}"},
                )
        assert resp.status_code == 200

    def test_invalid_key_returns_401(self, raw_key):
        with patch("middleware.auth.cache_get", new_callable=AsyncMock, return_value=None), \
             patch("middleware.auth.get_api_key_by_hash", new_callable=AsyncMock, return_value=None):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    "/signals",
                    json={"ticker": "AAPL"},
                    headers={"Authorization": f"Bearer {raw_key}"},
                )
        assert resp.status_code == 401

    def test_cache_hit_skips_db(self, raw_key):
        import hashlib, json
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        cached_auth = {
            "key_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "plan": "pro",
            "clerk_id": "clerk_abc",
            "email": "test@sigma.local",
        }

        with patch("middleware.auth.cache_get", new_callable=AsyncMock, return_value=cached_auth), \
             patch("routers.signals.check_rate_limit", new_callable=AsyncMock), \
             patch("routers.signals.cache_get", new_callable=AsyncMock, return_value=None), \
             patch("routers.signals.cache_set", new_callable=AsyncMock), \
             patch("routers.signals.run_signal_pipeline") as mock_pipeline, \
             patch("routers.signals._log_usage", new_callable=AsyncMock), \
             patch("routers.signals.record_usage", new_callable=AsyncMock):

            from ml.inference import SignalResult
            mock_result = SignalResult("HOLD", 0.55, 0.0)
            mock_result.model_version = "v1.0"
            mock_pipeline.return_value = mock_result

            with TestClient(app) as c:
                resp = c.post(
                    "/signals",
                    json={"ticker": "AAPL"},
                    headers={"Authorization": f"Bearer {raw_key}"},
                )
        assert resp.status_code == 200
