"""Model lifecycle endpoints — the human-approval surface for self-evolution.

The worker-internal scheduler trains candidates, evaluates them, and *proposes*
champion promotions (model_promotions, status=pending). Nothing auto-deploys.
A human reviews pending proposals here and approves/rejects:

  GET  /models/champions                  — active model version per asset class
  GET  /models/promotions?status=pending  — proposals awaiting a decision
  GET  /models/evaluations                — recent measured performance
  POST /models/promotions/{id}/approve    — activate the candidate (internal-auth)
  POST /models/promotions/{id}/reject     — decline (internal-auth)

Approve/reject mutate which model trades, so they require the internal secret
(same guard as execution.run_cycle); the GETs need a normal API key.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from db.models import ModelChampion, ModelEvaluation, ModelPromotion
from middleware.auth import AuthContext, require_auth
from ml.promotion import approve_promotion, reject_promotion

router = APIRouter(prefix="/models", tags=["models"])
AuthDep = Annotated[AuthContext, Depends(require_auth)]


class ChampionOut(BaseModel):
    asset_class: str
    model_type: str
    version: str
    updated_at: datetime


class PromotionOut(BaseModel):
    id: str
    asset_class: str
    model_type: str
    from_version: Optional[str]
    to_version: str
    status: str
    proposed_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    rationale: Optional[dict] = None


class EvaluationOut(BaseModel):
    id: str
    asset_class: str
    model_type: str
    model_version: str
    eval_date: datetime
    n_samples: int
    directional_accuracy: Optional[float] = None
    signal_accuracy: Optional[float] = None
    mean_abs_error: Optional[float] = None


@router.get("/champions", response_model=list[ChampionOut])
async def list_champions(auth: AuthDep, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ModelChampion).order_by(ModelChampion.asset_class))
    return [
        ChampionOut(asset_class=c.asset_class, model_type=c.model_type,
                    version=c.version, updated_at=c.updated_at)
        for c in res.scalars().all()
    ]


@router.get("/promotions", response_model=list[PromotionOut])
async def list_promotions(
    auth: AuthDep,
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(pending|approved|rejected)$"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(ModelPromotion).order_by(ModelPromotion.proposed_at.desc()).limit(limit)
    if status_filter:
        q = q.where(ModelPromotion.status == status_filter)
    res = await db.execute(q)
    return [_promo_out(p) for p in res.scalars().all()]


@router.get("/evaluations", response_model=list[EvaluationOut])
async def list_evaluations(
    auth: AuthDep,
    asset_class: Optional[str] = Query(None),
    model_version: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(ModelEvaluation).order_by(ModelEvaluation.eval_date.desc()).limit(limit)
    if asset_class:
        q = q.where(ModelEvaluation.asset_class == asset_class)
    if model_version:
        q = q.where(ModelEvaluation.model_version == model_version)
    res = await db.execute(q)
    return [
        EvaluationOut(
            id=str(e.id), asset_class=e.asset_class, model_type=e.model_type,
            model_version=e.model_version, eval_date=e.eval_date, n_samples=e.n_samples,
            directional_accuracy=float(e.directional_accuracy) if e.directional_accuracy is not None else None,
            signal_accuracy=float(e.signal_accuracy) if e.signal_accuracy is not None else None,
            mean_abs_error=float(e.mean_abs_error) if e.mean_abs_error is not None else None,
        )
        for e in res.scalars().all()
    ]


@router.post("/promotions/{promotion_id}/approve", response_model=PromotionOut)
async def approve(promotion_id: str, auth: AuthDep, db: AsyncSession = Depends(get_db)):
    _require_internal(auth)
    promo = await approve_promotion(db, _as_uuid(promotion_id), decided_by=_actor(auth))
    if promo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="promotion not found")
    await db.commit()
    return _promo_out(promo)


@router.post("/promotions/{promotion_id}/reject", response_model=PromotionOut)
async def reject(promotion_id: str, auth: AuthDep, db: AsyncSession = Depends(get_db)):
    _require_internal(auth)
    promo = await reject_promotion(db, _as_uuid(promotion_id), decided_by=_actor(auth))
    if promo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="promotion not found")
    await db.commit()
    return _promo_out(promo)


# ---- helpers --------------------------------------------------------------

def _require_internal(auth: AuthContext) -> None:
    if not auth.internal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="promotion decisions require X-Internal-Secret",
        )


def _actor(auth: AuthContext) -> str:
    return "internal" if auth.internal else "human"


def _as_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid promotion id") from exc


def _promo_out(p: ModelPromotion) -> PromotionOut:
    return PromotionOut(
        id=str(p.id), asset_class=p.asset_class, model_type=p.model_type,
        from_version=p.from_version, to_version=p.to_version, status=p.status,
        proposed_at=p.proposed_at, decided_at=p.decided_at, decided_by=p.decided_by,
        rationale=p.rationale,
    )
