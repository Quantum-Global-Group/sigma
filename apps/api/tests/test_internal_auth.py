"""Verify that the X-Internal-Secret header bypasses Stripe metering and
rate limits, but still results in a UsageLog row tagged internal=True."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.connection import get_db
from main import app
from middleware.auth import AuthContext, require_auth


SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _SystemUser:
    id = SYSTEM_USER_ID
    plan = "enterprise"
    clerk_id = "system:worker"
    email = "worker@sigma.internal"
    stripe_customer_id = None


@pytest.fixture
def internal_client():
    """Like the regular `client` fixture but resolves auth to the system user
    with internal=True, mirroring what require_auth does when the header
    matches settings.internal_secret."""
    from fastapi.testclient import TestClient
    from middleware.rate_limit import check_rate_limit

    async def _fake_auth_ctx():
        return AuthContext(api_key=None, user=_SystemUser(), internal=True)

    async def _fake_rate_limit(*args, **kwargs):
        return None

    async def _fake_db():
        s = MagicMock()
        s.add = MagicMock()
        s.commit = AsyncMock()
        s.close = AsyncMock()
        yield s

    app.dependency_overrides[require_auth] = _fake_auth_ctx
    app.dependency_overrides[check_rate_limit] = _fake_rate_limit
    app.dependency_overrides[get_db] = _fake_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_internal_request_skips_rate_limit_and_stripe(internal_client):
    from ml.inference import SignalResult

    mock_result = SignalResult("HOLD", 0.5, 0.0)
    mock_result.model_version = "v1.0"

    with patch("routers.signals.run_signal_pipeline", return_value=mock_result), \
         patch("routers.signals.cache_get", new_callable=AsyncMock, return_value=None), \
         patch("routers.signals.cache_set", new_callable=AsyncMock), \
         patch("routers.signals.check_rate_limit", new_callable=AsyncMock) as rate, \
         patch("routers.signals.record_usage", new_callable=AsyncMock) as stripe, \
         patch("routers.signals._log_usage", new_callable=AsyncMock) as log:
        resp = internal_client.post(
            "/signals",
            json={"ticker": "BTC-USD", "timeframe": "5m", "asset_class": "crypto"},
            headers={"X-Internal-Secret": "anything"},
        )

    assert resp.status_code == 200
    rate.assert_not_called()
    stripe.assert_not_called()
    # UsageLog still recorded — observability path is preserved
    log.assert_called_once()
    auth_arg = log.call_args.args[1]
    assert auth_arg.internal is True
