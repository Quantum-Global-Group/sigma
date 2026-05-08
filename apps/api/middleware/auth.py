import hashlib
from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cache.redis import cache_get, cache_set
from config import settings
from db.connection import get_db
from db.models import APIKey, User
from db.queries import get_api_key_by_hash, get_user_by_id, get_user_by_id_str


@dataclass
class AuthContext:
    """Result of the auth dependency. `internal=True` means the request came
    from the worker (or another internal service) via X-Internal-Secret and
    must skip Stripe metering and rate limits while still being logged."""

    api_key: Optional[APIKey]
    user: User
    internal: bool


async def _resolve_api_key(authorization: str, db: AsyncSession) -> tuple[APIKey, User]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    raw_key = authorization.removeprefix("Bearer ").strip()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    cache_key = f"api_key:{key_hash}"

    cached = await cache_get(cache_key)
    if cached:
        class _CachedKey:
            id = cached["key_id"]
            user_id = cached["user_id"]

        class _CachedUser:
            id = cached["user_id"]
            plan = cached["plan"]
            clerk_id = cached["clerk_id"]
            email = cached["email"]

        return _CachedKey(), _CachedUser()  # type: ignore[return-value]

    api_key = await get_api_key_by_hash(db, raw_key)
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    user = await get_user_by_id(db, api_key.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    await cache_set(
        cache_key,
        {"key_id": str(api_key.id), "user_id": str(user.id), "plan": user.plan, "clerk_id": user.clerk_id, "email": user.email},
        settings.redis_ttl_api_key,
    )
    return api_key, user


async def require_api_key(
    authorization: Annotated[str, Header(alias="Authorization")],
    db: AsyncSession = Depends(get_db),
) -> tuple[APIKey, User]:
    return await _resolve_api_key(authorization, db)


async def require_auth(
    authorization: Annotated[Optional[str], Header(alias="Authorization")] = None,
    x_internal_secret: Annotated[Optional[str], Header(alias="X-Internal-Secret")] = None,
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """Auth dependency that accepts either a customer API key or the worker's
    internal secret. Endpoints used by the worker should depend on this rather
    than `require_api_key` so internal traffic bypasses metering/rate-limit."""

    if x_internal_secret and settings.internal_secret and x_internal_secret == settings.internal_secret:
        system_user = await get_user_by_id_str(db, settings.system_user_id)
        if system_user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="System user not seeded — run migration 005",
            )
        return AuthContext(api_key=None, user=system_user, internal=True)

    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")

    api_key, user = await _resolve_api_key(authorization, db)
    return AuthContext(api_key=api_key, user=user, internal=False)
