"""Strategy-level performance reporting from signal_history."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from middleware.auth import AuthContext, require_auth
from ml.strategy_performance import fetch_strategy_performance, parse_period

router = APIRouter(prefix="/strategies", tags=["strategies"])
AuthDep = Annotated[AuthContext, Depends(require_auth)]


@router.get("/performance")
async def strategy_performance(
    auth: AuthDep,
    asset_class: str = Query("equity", pattern="^(equity|crypto|forex|option)$"),
    since: Optional[datetime] = Query(None, description="ISO timestamp — only signals after this time"),
    period: Optional[str] = Query(
        None,
        description="Rolling window (e.g. 7d, 24h). Overrides since when set.",
    ),
    strength_threshold: float = Query(0.3, ge=0.0, le=1.0,
                                      description="Min strategy strength for win-rate bucket"),
    limit: int = Query(5000, ge=1, le=50_000),
    db: AsyncSession = Depends(get_db),
):
    """Per-strategy contribution frequency, avg strength, and win rate above threshold."""
    if period is not None:
        try:
            parse_period(period)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await fetch_strategy_performance(
        db,
        asset_class=asset_class,
        since=since,
        period=period,
        strength_threshold=strength_threshold,
        limit=limit,
    )


@router.get("/performance/report")
async def strategy_performance_report(
    auth: AuthDep,
    asset_class: str = Query("equity", pattern="^(equity|crypto|forex|option)$"),
    period: str = Query("7d", description="Rolling window for the weekly report (default 7d)"),
    strength_threshold: float = Query(0.3, ge=0.0, le=1.0),
    limit: int = Query(5000, ge=1, le=50_000),
    db: AsyncSession = Depends(get_db),
):
    """Weekly-style strategy report: same stats as /performance plus markdown summary."""
    try:
        parse_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await fetch_strategy_performance(
        db,
        asset_class=asset_class,
        period=period,
        strength_threshold=strength_threshold,
        limit=limit,
        include_summary=True,
    )
