"""Model evaluation — score a model version against its labeled predictions.

Once ml/labeling.py has stamped realized outcomes onto signal_history, this
measures how well a given (asset_class, model_version) actually predicted:
  - directional_accuracy: sign(predicted_return) == sign(realized_return)
  - signal_accuracy:      win / (win + loss) over non-flat outcomes
  - mean_abs_error:       mean |predicted_return - realized_return|
and persists a `model_evaluations` row. These metrics are what the promotion
step compares between a candidate and the incumbent champion.

`compute_metrics` is pure (testable on plain rows); `evaluate_model` does the DB.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ModelEvaluation, SignalHistory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvalMetrics:
    n_samples: int
    directional_accuracy: Optional[float]
    signal_accuracy: Optional[float]
    mean_abs_error: Optional[float]

    def as_dict(self) -> dict:
        return {
            "n_samples": self.n_samples,
            "directional_accuracy": self.directional_accuracy,
            "signal_accuracy": self.signal_accuracy,
            "mean_abs_error": self.mean_abs_error,
        }


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def compute_metrics(rows: Sequence) -> EvalMetrics:
    """Compute eval metrics from labeled signal rows. Pure.

    Each row needs: predicted_return, realized_return, outcome. Rows missing a
    realized_return are ignored (unlabeled)."""
    dir_hits = dir_total = 0
    wins = losses = 0
    abs_err_sum = abs_err_n = 0.0
    n = 0

    for r in rows:
        rr = getattr(r, "realized_return", None)
        if rr is None:
            continue
        rr = float(rr)
        n += 1
        pr = getattr(r, "predicted_return", None)
        if pr is not None:
            pr = float(pr)
            abs_err_sum += abs(pr - rr)
            abs_err_n += 1
            if _sign(pr) != 0 and _sign(rr) != 0:
                dir_total += 1
                if _sign(pr) == _sign(rr):
                    dir_hits += 1
        outcome = (getattr(r, "outcome", None) or "").lower()
        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1

    directional = (dir_hits / dir_total) if dir_total else None
    signal_acc = (wins / (wins + losses)) if (wins + losses) else None
    mae = (abs_err_sum / abs_err_n) if abs_err_n else None
    return EvalMetrics(
        n_samples=n,
        directional_accuracy=round(directional, 4) if directional is not None else None,
        signal_accuracy=round(signal_acc, 4) if signal_acc is not None else None,
        mean_abs_error=round(mae, 6) if mae is not None else None,
    )


async def evaluate_model(
    session: AsyncSession,
    asset_class: str,
    model_version: str,
    *,
    model_type: str = "ensemble",
    backtest_sharpe: Optional[float] = None,
    backtest_win_rate: Optional[float] = None,
) -> ModelEvaluation:
    """Score a model version on its labeled signals and persist an evaluation row."""
    q = (
        select(SignalHistory)
        .where(SignalHistory.asset_class == asset_class)
        .where(SignalHistory.model_version == model_version)
        .where(SignalHistory.labeled_at.is_not(None))
    )
    rows = list((await session.execute(q)).scalars().all())
    m = compute_metrics(rows)

    row = ModelEvaluation(
        asset_class=asset_class, model_type=model_type, model_version=model_version,
        n_samples=m.n_samples, directional_accuracy=m.directional_accuracy,
        signal_accuracy=m.signal_accuracy, mean_abs_error=m.mean_abs_error,
        backtest_sharpe=backtest_sharpe, backtest_win_rate=backtest_win_rate,
        metrics=m.as_dict(),
    )
    session.add(row)
    logger.info("[eval] %s %s: n=%d dir_acc=%s sig_acc=%s",
                asset_class, model_version, m.n_samples, m.directional_accuracy, m.signal_accuracy)
    return row
