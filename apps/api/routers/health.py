from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from cache.redis import redis_ping
from db.connection import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/ready")
async def ready():
    errors: list[str] = []

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        errors.append(f"db: {exc}")

    if not await redis_ping():
        errors.append("redis: ping failed")

    if errors:
        return {"status": "degraded", "errors": errors}
    return {"status": "ok"}
