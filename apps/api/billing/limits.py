from config import settings

PLAN_LIMITS: dict[str, int] = {
    "free": settings.rate_limit_free,
    "pro": settings.rate_limit_pro,
    "enterprise": settings.rate_limit_enterprise,
}


def get_plan_limit(plan: str) -> int:
    """Return the daily API call limit for a plan."""
    return PLAN_LIMITS.get(plan, settings.rate_limit_free)


def check_limit(api_calls: int, plan: str) -> bool:
    """Return True if api_calls is within the plan limit."""
    return api_calls <= get_plan_limit(plan)
