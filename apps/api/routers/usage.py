from typing import Annotated
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from billing.limits import get_plan_limit
from db.connection import get_db
from db.models import APIKey, User
from db.queries import get_usage_this_period
from middleware.auth import require_api_key
from models.user import UsageSummary

router = APIRouter(prefix="/usage", tags=["usage"])

AuthDep = Annotated[tuple[APIKey, User], Depends(require_api_key)]


@router.get("", response_model=UsageSummary)
async def get_usage(auth: AuthDep, db: AsyncSession = Depends(get_db)):
    _, user = auth
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Last day of month: first day of next month minus one day
    if now.month == 12:
        period_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        period_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    api_calls = await get_usage_this_period(db, user.id)
    limit = get_plan_limit(user.plan)

    return UsageSummary(
        user_id=user.id,
        plan=user.plan,
        period_start=period_start.date().isoformat(),
        period_end=period_end.date().isoformat(),
        api_calls=api_calls,
        limit=limit,
        remaining=max(0, limit - api_calls),
    )
