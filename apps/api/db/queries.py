import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import APIKey, SignalHistory, UsageLog, User


async def get_api_key_by_hash(db: AsyncSession, raw_key: str) -> APIKey | None:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    result = await db.execute(
        select(APIKey)
        .where(APIKey.key_hash == key_hash)
        .where(APIKey.revoked.is_(False))
        .where((APIKey.expires_at.is_(None)) | (APIKey.expires_at > datetime.now(timezone.utc)))
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_id_str(db: AsyncSession, user_id: str) -> User | None:
    """Like get_user_by_id but accepts a UUID string (used by the worker auth
    bypass which reads settings.system_user_id as a string)."""
    return await get_user_by_id(db, uuid.UUID(user_id))


# ─── API key CRUD ────────────────────────────────────────────────────────────

async def list_keys_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[APIKey]:
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == user_id)
        .where(APIKey.revoked.is_(False))
        .order_by(APIKey.created_at.desc())
    )
    return list(result.scalars().all())


async def create_api_key(db: AsyncSession, user_id: uuid.UUID, name: str | None = None) -> tuple[APIKey, str]:
    """Generate a new API key, store its hash, return (ORM object, raw key)."""
    raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    api_key = APIKey(
        user_id=user_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key, raw_key


async def revoke_api_key(db: AsyncSession, key_id: uuid.UUID, user_id: uuid.UUID) -> APIKey | None:
    """Set revoked=True on a key owned by user_id. Returns the key or None if not found."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.id == key_id)
        .where(APIKey.user_id == user_id)
        .where(APIKey.revoked.is_(False))
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        return None
    api_key.revoked = True
    await db.commit()
    return api_key


# ─── Usage queries ───────────────────────────────────────────────────────────

async def get_usage_this_period(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Count UsageLog rows for user_id from the start of the current calendar month."""
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count(UsageLog.id))
        .where(UsageLog.user_id == user_id)
        .where(UsageLog.created_at >= period_start)
        .where(UsageLog.status_code < 400)
    )
    return result.scalar_one() or 0


# ─── Signal history queries ──────────────────────────────────────────────────

async def fetch_signal_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    ticker: str,
    timeframe: str = "daily",
    limit: int = 30,
    before: datetime | None = None,
) -> list[SignalHistory]:
    query = (
        select(SignalHistory)
        .where(SignalHistory.user_id == user_id)
        .where(SignalHistory.ticker == ticker.upper())
        .where(SignalHistory.timeframe == timeframe)
        .order_by(SignalHistory.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    if before is not None:
        query = query.where(SignalHistory.created_at < before)

    result = await db.execute(query)
    return list(result.scalars().all())
