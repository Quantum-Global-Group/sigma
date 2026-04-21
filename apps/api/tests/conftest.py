import hashlib
import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from db.connection import get_db
from main import app
from middleware.auth import require_api_key
from middleware.rate_limit import check_rate_limit

# ─── Test API key ────────────────────────────────────────────────────────────

RAW_TEST_KEY = f"sk_test_{secrets.token_urlsafe(32)}"
TEST_KEY_HASH = hashlib.sha256(RAW_TEST_KEY.encode()).hexdigest()
TEST_USER_ID = uuid.uuid4()
TEST_KEY_ID = uuid.uuid4()


class _FakeAPIKey:
    id = TEST_KEY_ID
    user_id = TEST_USER_ID
    stripe_customer_id = None


class _FakeUser:
    id = TEST_USER_ID
    plan = "pro"
    clerk_id = "test_clerk_id"
    email = "test@sigma.local"
    stripe_customer_id = None


MOCK_AUTH = (_FakeAPIKey(), _FakeUser())


async def _fake_db():
    """Yield a no-op async session mock — prevents real DB calls in unit tests."""
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.close = AsyncMock()
    yield mock_session


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {RAW_TEST_KEY}"}


@pytest.fixture
def client():
    """
    TestClient with dependency overrides for auth, rate-limit, and DB.
    _log_usage is also patched out to avoid asyncio.create_task DB teardown issues.
    """
    async def _fake_auth():
        return MOCK_AUTH

    async def _fake_rate_limit(*args, **kwargs):
        return None

    app.dependency_overrides[require_api_key] = _fake_auth
    app.dependency_overrides[check_rate_limit] = _fake_rate_limit
    app.dependency_overrides[get_db] = _fake_db

    with patch("routers.signals._log_usage", new_callable=AsyncMock), \
         patch("routers.signals.record_usage", new_callable=AsyncMock):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def mock_cache_miss():
    with patch("routers.signals.cache_get", new_callable=AsyncMock, return_value=None), \
         patch("routers.signals.cache_set", new_callable=AsyncMock):
        yield
