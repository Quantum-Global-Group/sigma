import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from billing.stripe import record_usage
from cache.redis import cache_get, cache_set
from config import settings
from db.connection import get_db
from db.models import UsageLog, User
from db.queries import fetch_signal_history
from middleware.auth import AuthContext, require_auth
from middleware.rate_limit import check_rate_limit
from ml.pipeline import run_signal_pipeline
from models.signal import SignalRequest, SignalResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signals", tags=["signals"])

AuthDep = Annotated[AuthContext, Depends(require_auth)]


async def _log_usage(
    db: AsyncSession,
    auth: AuthContext,
    ticker: str,
    status_code: int,
    response_ms: int,
) -> None:
    try:
        log = UsageLog(
            user_id=auth.user.id,
            api_key_id=auth.api_key.id if auth.api_key is not None else None,
            endpoint="/signals",
            ticker=ticker,
            response_ms=response_ms,
            status_code=status_code,
            internal=auth.internal,
        )
        db.add(log)
        await db.commit()
    except Exception as exc:
        logger.warning("UsageLog insert failed: %s", exc)


@router.post("", response_model=SignalResponse)
async def generate_signal(body: SignalRequest, auth: AuthDep, db: AsyncSession = Depends(get_db)):
    if not auth.internal:
        await check_rate_limit(auth.user)
    t_start = datetime.now(timezone.utc)

    cache_key = f"signal:{body.asset_class}:{body.ticker}:{body.timeframe}"
    cached = await cache_get(cache_key)
    if cached:
        elapsed = int((datetime.now(timezone.utc) - t_start).total_seconds() * 1000)
        asyncio.create_task(_log_usage(db, auth, body.ticker, 200, elapsed))
        return SignalResponse(**{**cached, "cached": True})

    try:
        result = run_signal_pipeline(body.ticker, body.timeframe, asset_class=body.asset_class)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    now = datetime.now(timezone.utc)
    elapsed = int((now - t_start).total_seconds() * 1000)
    payload = {
        "ticker": body.ticker,
        "timeframe": body.timeframe,
        "asset_class": body.asset_class,
        "signal": result.signal,
        "confidence": result.confidence,
        "predicted_return": result.predicted_return,
        "model_version": result.model_version,
        "timestamp": now.isoformat(),
        "cached": False,
        "component_weights": getattr(result, "component_weights", None),
    }

    await cache_set(cache_key, payload, settings.redis_ttl_signal)

    asyncio.create_task(_log_usage(db, auth, body.ticker, 200, elapsed))
    if not auth.internal:
        stripe_customer_id = getattr(auth.user, "stripe_customer_id", None)
        asyncio.create_task(record_usage(stripe_customer_id))

    return SignalResponse(**payload)


@router.get("/{ticker}/history", response_model=list[SignalResponse])
async def signal_history(
    ticker: str,
    auth: AuthDep,
    timeframe: str = Query("daily", pattern="^(daily|4h|hourly|5m|1m)$"),
    limit: int = Query(30, ge=1, le=200),
    before: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    rows = await fetch_signal_history(db, auth.user.id, ticker, timeframe, limit, before)
    return [
        SignalResponse(
            ticker=row.ticker,
            timeframe=row.timeframe,
            asset_class=getattr(row, "asset_class", None) or "equity",
            signal=row.signal,
            confidence=float(row.confidence),
            predicted_return=float(row.predicted_return) if row.predicted_return is not None else 0.0,
            model_version=row.model_version,
            cached=False,
            timestamp=row.created_at,
            component_weights=getattr(row, "component_weights", None),
        )
        for row in rows
    ]
