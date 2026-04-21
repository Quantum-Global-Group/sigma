"""
Internal endpoints called only by trusted services (Clerk webhooks, etc.).
Protected by a shared secret header, NOT by user API key auth.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from config import settings
from db.connection import get_db
from db.models import User
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


class UserUpsertPayload(BaseModel):
    clerk_id: str
    email: str
    plan: str = "free"


class SyncPlanPayload(BaseModel):
    stripe_customer_id: str
    plan: str


async def _verify_internal(x_internal_secret: str = Header(alias="X-Internal-Secret")) -> None:
    if x_internal_secret != settings.secret_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.post("/users/upsert", dependencies=[Depends(_verify_internal)])
async def upsert_user(payload: UserUpsertPayload, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.clerk_id == payload.clerk_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            clerk_id=payload.clerk_id,
            email=payload.email,
            plan=payload.plan,
        )
        db.add(user)
        logger.info("Created user clerk_id=%s", payload.clerk_id)
    else:
        user.email = payload.email
        if payload.plan != "free":
            user.plan = payload.plan
        logger.info("Updated user clerk_id=%s", payload.clerk_id)

    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "clerk_id": user.clerk_id, "plan": user.plan}


@router.post("/users/sync-plan", dependencies=[Depends(_verify_internal)])
async def sync_plan(payload: SyncPlanPayload, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.stripe_customer_id == payload.stripe_customer_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.plan = payload.plan
    await db.commit()
    logger.info("Synced plan for customer %s → %s", payload.stripe_customer_id, payload.plan)
    return {"plan": user.plan}
