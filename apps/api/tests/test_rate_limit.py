"""
Tests for the Redis sliding-window rate limiter.
All Redis calls are mocked — no live services needed.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from middleware.rate_limit import BURST_LIMITS, PLAN_LIMITS, check_rate_limit


def _make_user(plan: str = "free") -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.plan = plan
    return user


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_within_limits_does_not_raise(self):
        user = _make_user("pro")
        mock_pipe = AsyncMock()
        # [day_count=1, _, min_count=1, _]
        mock_pipe.execute = AsyncMock(return_value=[1, True, 1, True])

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("middleware.rate_limit.get_redis", return_value=mock_redis):
            await check_rate_limit(user)  # should not raise

    @pytest.mark.asyncio
    async def test_daily_limit_exceeded_raises_429(self):
        user = _make_user("free")
        day_limit = PLAN_LIMITS["free"]
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[day_limit + 1, True, 1, True])

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("middleware.rate_limit.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await check_rate_limit(user)
        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_burst_limit_exceeded_raises_429(self):
        user = _make_user("pro")
        burst_limit = BURST_LIMITS["pro"]
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[1, True, burst_limit + 1, True])

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("middleware.rate_limit.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await check_rate_limit(user)
        assert exc_info.value.status_code == 429
        assert "Burst" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_unknown_plan_falls_back_to_free(self):
        user = _make_user("unknown_plan")
        free_limit = PLAN_LIMITS["free"]
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[free_limit + 1, True, 1, True])

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("middleware.rate_limit.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await check_rate_limit(user)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_enterprise_has_high_limit(self):
        user = _make_user("enterprise")
        mock_pipe = AsyncMock()
        # 10,000 calls — well within enterprise limit
        mock_pipe.execute = AsyncMock(return_value=[10_000, True, 1, True])

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("middleware.rate_limit.get_redis", return_value=mock_redis):
            await check_rate_limit(user)  # should not raise
