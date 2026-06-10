import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.connection import get_db
from db.models import APIKey, EquitySnapshot, PortfolioSnapshot, Position, User
from middleware.auth import AuthContext, require_api_key, require_auth
from middleware.rate_limit import check_rate_limit
from models.portfolio import PortfolioRequest, RebalanceResponse, TradeRecommendation
from quantum.portfolio_optimizer import optimize
from risk.portfolio_pnl import aggregate_pnl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

AuthDep = Annotated[tuple[APIKey, User], Depends(require_api_key)]
ReadAuthDep = Annotated[AuthContext, Depends(require_auth)]


async def _persist_snapshot(db: AsyncSession, user: User, body: PortfolioRequest, result: dict) -> None:
    try:
        snapshot = PortfolioSnapshot(
            user_id=user.id,
            holdings=body.holdings,
            total_value=sum(body.holdings.values()),
            optimization_method=result["method"],
            target_allocation=result["target_allocation"],
            recommended_trades=result["recommended_trades"],
            sharpe_ratio=result.get("sharpe_ratio"),
        )
        db.add(snapshot)
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to persist portfolio snapshot: %s", exc)


@router.post("/rebalance", response_model=RebalanceResponse)
async def rebalance(body: PortfolioRequest, auth: AuthDep, db: AsyncSession = Depends(get_db)):
    _, user = auth
    await check_rate_limit(user)

    try:
        result = await optimize(body.holdings, body.method, body.risk_aversion)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Optimization failed")

    asyncio.create_task(_persist_snapshot(db, user, body, result))

    return RebalanceResponse(
        method=result["method"],
        fallback=result["fallback"],
        target_allocation=result["target_allocation"],
        recommended_trades=[TradeRecommendation(**t) for t in result["recommended_trades"]],
        sharpe_ratio=result.get("sharpe_ratio"),
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# P&L reporting — live aggregate + equity curve (read-only, dashboard)
# ---------------------------------------------------------------------------

class PnlResponse(BaseModel):
    total_realized: float
    total_unrealized: float
    total_pnl: float
    open_positions: int
    by_asset_class: dict
    base_equity: float
    total_value: float


class EquityPoint(BaseModel):
    ts: datetime
    base_equity: float
    total_realized: float
    total_unrealized: float
    total_value: float


@router.get("/pnl", response_model=PnlResponse)
async def portfolio_pnl(auth: ReadAuthDep, db: AsyncSession = Depends(get_db)):
    """Live aggregate P&L across the house book — total realized + unrealized,
    broken down by asset class. Open positions are marked-to-market each tick."""
    res = await db.execute(select(Position))
    summary = aggregate_pnl(res.scalars().all())
    base = float(settings.default_equity)
    d = summary.to_dict()
    return PnlResponse(
        **d,
        base_equity=round(base, 2),
        total_value=round(base + summary.total_pnl, 2),
    )


@router.get("/equity-curve", response_model=list[EquityPoint])
async def equity_curve(
    auth: ReadAuthDep,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Account-value time series from the daily equity snapshots."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = await db.execute(
        select(EquitySnapshot).where(EquitySnapshot.ts >= cutoff).order_by(EquitySnapshot.ts.asc())
    )
    return [
        EquityPoint(
            ts=row.ts, base_equity=float(row.base_equity),
            total_realized=float(row.total_realized),
            total_unrealized=float(row.total_unrealized),
            total_value=float(row.total_value),
        )
        for row in res.scalars().all()
    ]
