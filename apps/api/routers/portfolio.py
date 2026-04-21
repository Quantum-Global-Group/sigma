import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from db.models import APIKey, PortfolioSnapshot, User
from middleware.auth import require_api_key
from middleware.rate_limit import check_rate_limit
from models.portfolio import PortfolioRequest, RebalanceResponse, TradeRecommendation
from quantum.portfolio_optimizer import optimize

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

AuthDep = Annotated[tuple[APIKey, User], Depends(require_api_key)]


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
