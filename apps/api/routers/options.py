"""Options data endpoints — candidates, positions, and portfolio Greeks exposure.

Read-only. Designed for the dashboard to surface what the options worker is
seeing: ranked candidate trades (live chain + signal), open option positions
(with contract metadata), and the net-Greeks exposure of the current book.

All endpoints require a valid API key (require_auth) — same as positions/orders.
The chain-fetch endpoints degrade gracefully when OpenD is not reachable: they
return an empty list rather than a 500 so the dashboard stays usable.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from db.models import Position
from middleware.auth import AuthContext, require_auth
from risk.greeks import GreekExposure, GreekLimits, aggregate_greeks, check_greek_limits
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/options", tags=["options"])


def _nearest_expiry(expiries: list[date], min_dte: int = 14, max_dte: int = 60) -> Optional[date]:
    """Nearest expiry in [min_dte, max_dte] days from today (shared with options worker)."""
    today = date.today()
    cands = [e for e in expiries if min_dte <= (e - today).days <= max_dte]
    return min(cands) if cands else None
AuthDep = Annotated[AuthContext, Depends(require_auth)]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class NetGreeks(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float


class CandidateOut(BaseModel):
    underlying: str
    strategy: str
    score: float
    liquidity: float
    alignment: float
    risk_reward: float
    regime: str
    iv_rank: float
    net_delta: float
    max_loss: float
    max_profit: float          # may be very large (inf → 9999999)
    breakevens: list[float]
    rationale: dict


class OptionPositionOut(BaseModel):
    id: str
    symbol: str
    underlying: Optional[str]
    expiry: Optional[str]      # ISO date
    strike: Optional[float]
    right: Optional[str]
    multiplier: Optional[int]
    qty: float
    entry_px: float
    current_px: Optional[float]
    unrealized_pnl: Optional[float]
    realized_pnl: float
    closed: bool
    meta: Optional[dict]


class ExposureOut(BaseModel):
    net_greeks: NetGreeks
    positions_count: int
    greek_limits_ok: bool
    greek_breaches: list[str]


# ---------------------------------------------------------------------------
# GET /options/candidates
# ---------------------------------------------------------------------------

@router.get("/candidates", response_model=list[CandidateOut])
async def option_candidates(
    auth: AuthDep,
    underlying: str = Query(..., min_length=1, max_length=10, description="Underlying ticker (e.g. AAPL)"),
    expiry: Optional[str] = Query(None, description="Expiry date YYYY-MM-DD; omit for nearest"),
):
    """Ranked candidate option structures for an underlying.

    Fetches the live chain from OpenD (via MoomooOptionData), computes regime +
    underlying signal, then runs select_candidates. Returns an empty list —
    rather than an error — when OpenD is unreachable or the chain is empty.
    """
    underlying = underlying.upper()

    # Resolve expiry or pick nearest from OpenD.
    expiry_date: Optional[date] = None
    if expiry:
        try:
            expiry_date = date.fromisoformat(expiry)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"expiry must be YYYY-MM-DD, got {expiry!r}")

    try:
        from markets.options import MoomooOptionData
        opt = MoomooOptionData()

        if expiry_date is None:
            expiries = opt.list_expiries(underlying)
            expiry_date = _nearest_expiry(expiries)
            if expiry_date is None:
                return []

        chain_contracts = opt.get_chain(underlying, expiry_date)
        chain_quotes = opt.get_quotes(chain_contracts) if chain_contracts else []
        if not chain_quotes:
            return []
    except Exception:
        logger.warning("[options/candidates] OpenD unavailable for %s", underlying, exc_info=True)
        return []

    # Compute spot, regime, IV rank from underlying candles.
    try:
        from markets import get_market_adapter
        from ml.sequences import FeatureEngineer
        from ml.regime import RegimeDetector, Regime
        from ml.strategies import build_default_combiner, combine_to_result
        from options_math import realized_vol, iv_rank

        adapter = get_market_adapter("option")
        df = adapter.fetch_ohlcv(underlying, "daily")
        if df.empty or len(df) < 20:
            return []

        fe = FeatureEngineer()
        feats = fe.compute(df)
        spot = float(feats["c"].iloc[-1]) if "c" in feats.columns else float(df["close"].iloc[-1])
        prices = df["close"].astype(float).tolist()

        try:
            regime_result = RegimeDetector().fit(prices).label_latest()
            regime = regime_result.regime
        except Exception:
            regime = Regime.UNKNOWN

        combiner = build_default_combiner("equity")
        combined = combiner.combine_signals(underlying, feats, spot, model_predictions={})
        result_obj = combine_to_result(combined)

        rv = realized_vol(prices[-60:]) if len(prices) >= 60 else realized_vol(prices)
        iv_rank_val = iv_rank(rv, prices[-252:]) if len(prices) >= 252 else 0.5
        T = max(0.001, (expiry_date - date.today()).days / 365.0)
    except Exception:
        logger.warning("[options/candidates] signal compute failed for %s", underlying, exc_info=True)
        return []

    # Select candidates.
    try:
        from options import select_candidates
        from options_math import LiquidityFilters

        filters = LiquidityFilters(
            max_spread_pct=settings.option_max_spread_pct,
            min_volume=settings.option_min_volume,
            min_open_interest=settings.option_min_open_interest,
        )
        candidates = select_candidates(
            chain=chain_quotes, spot=spot,
            strength=combined.strength, regime=regime,
            iv_rank=iv_rank_val, T=T, r=0.05, filters=filters,
        )
    except Exception:
        logger.warning("[options/candidates] selection failed for %s", underlying, exc_info=True)
        return []

    out: list[CandidateOut] = []
    for c in candidates:
        max_profit = c.structure.max_profit
        if max_profit == float("inf"):
            max_profit = 9_999_999.0
        out.append(CandidateOut(
            underlying=underlying,
            strategy=c.strategy,
            score=c.score,
            liquidity=c.liquidity,
            alignment=c.alignment,
            risk_reward=c.risk_reward,
            regime=regime.value,
            iv_rank=round(iv_rank_val, 4),
            net_delta=round(c.structure.net_greeks.get("delta", 0.0), 4),
            max_loss=round(c.structure.max_loss, 2),
            max_profit=round(max_profit, 2),
            breakevens=c.structure.breakevens,
            rationale=c.rationale,
        ))
    return out


# ---------------------------------------------------------------------------
# GET /options/positions
# ---------------------------------------------------------------------------

@router.get("/positions", response_model=list[OptionPositionOut])
async def option_positions(
    auth: AuthDep,
    open_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Open (or recent) option positions with contract metadata."""
    q = (
        select(Position)
        .where(Position.asset_class == "option")
        .order_by(Position.entry_ts.desc())
        .limit(limit)
    )
    if open_only:
        q = q.where(Position.closed.is_(False))

    res = await db.execute(q)
    rows = res.scalars().all()
    return [
        OptionPositionOut(
            id=str(row.id),
            symbol=row.symbol,
            underlying=row.underlying,
            expiry=row.expiry.isoformat() if row.expiry else None,
            strike=float(row.strike) if row.strike is not None else None,
            right=row.right,
            multiplier=int(row.multiplier) if row.multiplier is not None else None,
            qty=float(row.qty),
            entry_px=float(row.entry_px),
            current_px=float(row.current_px) if row.current_px is not None else None,
            unrealized_pnl=float(row.unrealized_pnl) if row.unrealized_pnl is not None else None,
            realized_pnl=float(row.realized_pnl),
            closed=row.closed,
            meta=row.meta,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /options/exposure
# ---------------------------------------------------------------------------

@router.get("/exposure", response_model=ExposureOut)
async def option_exposure(
    auth: AuthDep,
    db: AsyncSession = Depends(get_db),
):
    """Net-Greeks exposure across all open option positions.

    Reads Greeks from the `meta` JSONB column written by the options worker.
    Returns zero exposure when there are no open positions.
    """
    q = (
        select(Position)
        .where(Position.asset_class == "option")
        .where(Position.closed.is_(False))
    )
    res = await db.execute(q)
    rows = res.scalars().all()

    position_dicts = []
    for row in rows:
        greeks = {}
        if row.meta and isinstance(row.meta, dict):
            greeks = row.meta.get("net_greeks", {})
        position_dicts.append({
            "greeks": greeks,
            "qty": float(row.qty),
            "multiplier": int(row.multiplier) if row.multiplier else 100,
        })

    net: GreekExposure = aggregate_greeks(position_dicts)
    limits = GreekLimits(
        max_abs_net_delta=settings.option_max_net_delta,
        max_abs_net_gamma=settings.option_max_net_gamma,
        max_abs_net_vega=settings.option_max_net_vega,
    )
    ok, breaches = check_greek_limits(net, limits)

    return ExposureOut(
        net_greeks=NetGreeks(delta=net.delta, gamma=net.gamma, theta=net.theta, vega=net.vega),
        positions_count=len(rows),
        greek_limits_ok=ok,
        greek_breaches=breaches,
    )
