"""Model promotion — propose (automatic) → approve (human) → champion (active).

The self-evolution loop never auto-deploys a model. When a freshly-trained
candidate beats the incumbent champion on labeled-signal accuracy by a margin
(and on enough samples), `propose_promotion` files a `model_promotions` row with
status='pending' and the metric deltas. A human reviews it via routers/models.py
and calls `approve_promotion` (→ upserts `model_champions`, the version the worker
then serves) or `reject_promotion`.

`get_champion_version` is what the worker reads each tick to pick its model.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import ModelChampion, ModelEvaluation, ModelPromotion

logger = logging.getLogger(__name__)


async def get_champion_version(session: AsyncSession, asset_class: str) -> Optional[str]:
    """Active model version for an asset class, or None (worker falls back to default)."""
    q = (
        select(ModelChampion.version)
        .where(ModelChampion.asset_class == asset_class)
        .order_by(ModelChampion.updated_at.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _latest_eval(session: AsyncSession, asset_class: str, model_type: str,
                       version: str) -> Optional[ModelEvaluation]:
    q = (
        select(ModelEvaluation)
        .where(ModelEvaluation.asset_class == asset_class)
        .where(ModelEvaluation.model_type == model_type)
        .where(ModelEvaluation.model_version == version)
        .order_by(ModelEvaluation.eval_date.desc())
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none()


async def _pending_exists(session: AsyncSession, asset_class: str, model_type: str,
                          to_version: str) -> bool:
    q = (
        select(ModelPromotion.id)
        .where(ModelPromotion.asset_class == asset_class)
        .where(ModelPromotion.model_type == model_type)
        .where(ModelPromotion.to_version == to_version)
        .where(ModelPromotion.status == "pending")
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none() is not None


async def propose_promotion(
    session: AsyncSession,
    asset_class: str,
    candidate_version: str,
    *,
    model_type: str = "ensemble",
    min_improvement: Optional[float] = None,
    min_samples: Optional[int] = None,
) -> Optional[ModelPromotion]:
    """File a pending promotion if the candidate beats the incumbent. Never activates.

    Gate: candidate has >= min_samples labeled signals AND its directional
    accuracy exceeds the incumbent's by >= min_improvement. Returns the new
    ModelPromotion or None (not better / not enough data / already proposed)."""
    min_imp = min_improvement if min_improvement is not None else settings.promotion_min_improvement
    min_n = min_samples if min_samples is not None else settings.promotion_min_samples

    cand = await _latest_eval(session, asset_class, model_type, candidate_version)
    if cand is None or cand.directional_accuracy is None or cand.n_samples < min_n:
        return None

    incumbent_version = await get_champion_version(session, asset_class) or settings.model_version
    if incumbent_version == candidate_version:
        return None
    incumbent = await _latest_eval(session, asset_class, model_type, incumbent_version)
    incumbent_acc = float(incumbent.directional_accuracy) if (incumbent and incumbent.directional_accuracy is not None) else 0.0
    cand_acc = float(cand.directional_accuracy)

    if cand_acc < incumbent_acc + min_imp:
        return None
    if await _pending_exists(session, asset_class, model_type, candidate_version):
        return None

    promo = ModelPromotion(
        asset_class=asset_class, model_type=model_type,
        from_version=incumbent_version, to_version=candidate_version, status="pending",
        rationale={
            "candidate_directional_accuracy": cand_acc,
            "incumbent_directional_accuracy": incumbent_acc,
            "improvement": round(cand_acc - incumbent_acc, 4),
            "candidate_n_samples": cand.n_samples,
            "min_improvement": min_imp, "min_samples": min_n,
        },
    )
    session.add(promo)
    logger.info("[promote] proposed %s %s → %s (+%.4f dir_acc)",
                asset_class, incumbent_version, candidate_version, cand_acc - incumbent_acc)
    return promo


async def _set_champion(session: AsyncSession, asset_class: str, model_type: str, version: str) -> None:
    stmt = pg_insert(ModelChampion).values(
        asset_class=asset_class, model_type=model_type, version=version,
        updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=["asset_class", "model_type"],
        set_={"version": version, "updated_at": datetime.now(timezone.utc)},
    )
    await session.execute(stmt)


async def approve_promotion(session: AsyncSession, promotion_id, decided_by: str = "human") -> Optional[ModelPromotion]:
    """Approve a pending promotion → upsert the champion to its to_version."""
    promo = await session.get(ModelPromotion, promotion_id)
    if promo is None or promo.status != "pending":
        return promo
    promo.status = "approved"
    promo.decided_at = datetime.now(timezone.utc)
    promo.decided_by = decided_by
    await _set_champion(session, promo.asset_class, promo.model_type, promo.to_version)
    logger.info("[promote] APPROVED %s %s → %s by %s",
                promo.asset_class, promo.from_version, promo.to_version, decided_by)
    return promo


async def reject_promotion(session: AsyncSession, promotion_id, decided_by: str = "human") -> Optional[ModelPromotion]:
    promo = await session.get(ModelPromotion, promotion_id)
    if promo is None or promo.status != "pending":
        return promo
    promo.status = "rejected"
    promo.decided_at = datetime.now(timezone.utc)
    promo.decided_by = decided_by
    return promo
