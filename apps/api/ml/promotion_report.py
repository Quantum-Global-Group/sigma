"""Structured promotion report — candidate vs incumbent comparison."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import ModelEvaluation, ModelPromotion
from ml.promotion import get_champion_version


async def build_promotion_report(session: AsyncSession, promotion_id) -> Optional[dict[str, Any]]:
    promo = await session.get(ModelPromotion, promotion_id)
    if promo is None:
        return None

    incumbent_version = promo.from_version or await get_champion_version(
        session, promo.asset_class,
    ) or settings.model_version

    async def _eval(version: str) -> Optional[ModelEvaluation]:
        q = (
            select(ModelEvaluation)
            .where(ModelEvaluation.asset_class == promo.asset_class)
            .where(ModelEvaluation.model_type == promo.model_type)
            .where(ModelEvaluation.model_version == version)
            .order_by(ModelEvaluation.eval_date.desc())
            .limit(1)
        )
        return (await session.execute(q)).scalar_one_or_none()

    cand_eval = await _eval(promo.to_version)
    inc_eval = await _eval(incumbent_version) if incumbent_version else None

    def _eval_dict(e: Optional[ModelEvaluation]) -> Optional[dict[str, Any]]:
        if e is None:
            return None
        return {
            "model_version": e.model_version,
            "eval_date": e.eval_date.isoformat() if e.eval_date else None,
            "n_samples": e.n_samples,
            "directional_accuracy": float(e.directional_accuracy) if e.directional_accuracy is not None else None,
            "signal_accuracy": float(e.signal_accuracy) if e.signal_accuracy is not None else None,
            "mean_abs_error": float(e.mean_abs_error) if e.mean_abs_error is not None else None,
            "backtest_sharpe": float(e.backtest_sharpe) if e.backtest_sharpe is not None else None,
            "backtest_win_rate": float(e.backtest_win_rate) if e.backtest_win_rate is not None else None,
            "metrics": e.metrics,
            "notes": e.notes,
        }

    cand_d = _eval_dict(cand_eval)
    inc_d = _eval_dict(inc_eval)
    rationale = promo.rationale or {}

    comparison: dict[str, Any] = {}
    if cand_d and inc_d:
        for key in ("directional_accuracy", "signal_accuracy", "mean_abs_error", "backtest_sharpe", "backtest_win_rate"):
            c_val = cand_d.get(key)
            i_val = inc_d.get(key)
            if c_val is not None and i_val is not None:
                comparison[f"{key}_delta"] = round(c_val - i_val, 6)

    recommendation = "review"
    if promo.status == "approved":
        recommendation = "promoted"
    elif promo.status == "rejected":
        recommendation = "rejected"
    elif cand_d and inc_d:
        c_acc = cand_d.get("directional_accuracy")
        i_acc = inc_d.get("directional_accuracy")
        if c_acc is not None and i_acc is not None and c_acc > i_acc:
            recommendation = "candidate_leads"

    return {
        "promotion": {
            "id": str(promo.id),
            "asset_class": promo.asset_class,
            "model_type": promo.model_type,
            "from_version": promo.from_version,
            "to_version": promo.to_version,
            "status": promo.status,
            "proposed_at": promo.proposed_at.isoformat() if promo.proposed_at else None,
            "decided_at": promo.decided_at.isoformat() if promo.decided_at else None,
            "decided_by": promo.decided_by,
            "rationale": rationale,
        },
        "incumbent": inc_d,
        "candidate": cand_d,
        "comparison": comparison,
        "recommendation": recommendation,
        "summary": _markdown_summary(promo, inc_d, cand_d, rationale, comparison),
    }


def _markdown_summary(promo, incumbent, candidate, rationale, comparison) -> str:
    lines = [
        f"# Promotion report: {promo.asset_class} {promo.from_version} → {promo.to_version}",
        "",
        f"Status: **{promo.status}**",
        "",
    ]
    if rationale:
        lines.append("## Proposal rationale")
        for k, v in rationale.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    if incumbent and candidate:
        lines.append("## Metrics")
        lines.append(f"| metric | incumbent ({incumbent['model_version']}) | candidate ({candidate['model_version']}) | delta |")
        lines.append("|---|---|---|---|")
        for key in ("directional_accuracy", "signal_accuracy", "n_samples"):
            i_v = incumbent.get(key)
            c_v = candidate.get(key)
            delta = comparison.get(f"{key}_delta", "—") if key != "n_samples" else (c_v - i_v if c_v is not None and i_v is not None else "—")
            lines.append(f"| {key} | {i_v} | {c_v} | {delta} |")
    return "\n".join(lines)
