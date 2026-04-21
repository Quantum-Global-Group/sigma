from datetime import datetime, timezone

from fastapi import HTTPException, status

from cache.redis import get_redis
from config import settings
from db.models import User

PLAN_LIMITS: dict[str, int] = {
    "free": settings.rate_limit_free,
    "pro": settings.rate_limit_pro,
    "enterprise": settings.rate_limit_enterprise,
}

BURST_LIMITS: dict[str, int] = {
    "free": 10,
    "pro": 200,
    "enterprise": 2000,
}


async def check_rate_limit(user: User) -> None:
    r = get_redis()
    plan = user.plan if user.plan in PLAN_LIMITS else "free"
    day_limit = PLAN_LIMITS[plan]
    burst_limit = BURST_LIMITS[plan]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_key = f"rl:day:{user.id}:{today}"
    minute_key = f"rl:min:{user.id}:{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')}"

    pipe = r.pipeline()
    pipe.incr(day_key)
    pipe.expire(day_key, 86400)
    pipe.incr(minute_key)
    pipe.expire(minute_key, 60)
    results = await pipe.execute()

    day_count, _, min_count, _ = results

    if day_count > day_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"X-RateLimit-Limit": str(day_limit), "X-RateLimit-Remaining": "0"},
        )

    if min_count > burst_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Burst rate limit exceeded",
            headers={"X-RateLimit-Limit": str(burst_limit), "X-RateLimit-Remaining": "0"},
        )
