"""Train-time promotion gate — refuse to ship an unmeasured or edgeless model.

Complements ml/evaluation.py (which scores models *after* deployment from
labeled signal_history rows): this gate runs at *training* time on the
chronological validation tail, before the artifact is written. A model that
can't beat the majority-class baseline, or whose directional score has no
positive rank correlation with realized next-bar returns, never reaches the
registry — the worker keeps trading the previous artifact (or the technical
blend) instead of silently absorbing a regression.

All functions are pure; scripts/train_models.py owns the IO and the
refuse-to-save behavior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np


def majority_baseline(y: Sequence[int]) -> float:
    """Accuracy of always predicting the most frequent class in `y`."""
    arr = np.asarray(y)
    if arr.size == 0:
        return 0.0
    _, counts = np.unique(arr, return_counts=True)
    return float(counts.max() / arr.size)


def rank_ic(scores: Sequence[float], returns: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation of model scores vs realized returns.

    Returns None when undefined (fewer than 3 pairs, or either side constant —
    a degenerate model that emits one score for every bar has no measurable
    edge, and the gate treats None as a failure)."""
    s = np.asarray(scores, dtype=float)
    r = np.asarray(returns, dtype=float)
    if s.size < 3 or s.size != r.size:
        return None
    if np.allclose(s, s[0]) or np.allclose(r, r[0]):
        return None
    from scipy.stats import spearmanr

    ic = spearmanr(s, r).statistic
    if ic is None or (isinstance(ic, float) and math.isnan(ic)):
        return None
    return float(ic)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    val_accuracy: float
    majority_baseline: float
    rank_ic: Optional[float]
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "val_accuracy": round(self.val_accuracy, 4),
            "majority_baseline": round(self.majority_baseline, 4),
            "rank_ic": round(self.rank_ic, 4) if self.rank_ic is not None else None,
            "reasons": list(self.reasons),
        }


def evaluate_train_gate(
    y_val: Sequence[int],
    val_pred: Sequence[int],
    val_scores: Sequence[float],
    val_returns: Sequence[float],
) -> GateResult:
    """Decide whether a freshly trained model earned its artifact.

    Fails when validation accuracy doesn't beat always-predict-majority, or
    when the directional score's rank-IC against realized returns is absent
    or non-positive. Both checks run on the chronological holdout only.
    """
    y_arr = np.asarray(y_val)
    pred_arr = np.asarray(val_pred)
    acc = float((y_arr == pred_arr).mean()) if y_arr.size else 0.0
    base = majority_baseline(y_arr)
    ic = rank_ic(val_scores, val_returns)

    reasons: list[str] = []
    if acc <= base:
        reasons.append(
            f"val_accuracy {acc:.4f} does not beat majority-class baseline {base:.4f}"
        )
    if ic is None:
        reasons.append("rank_ic undefined (constant scores/returns or too few samples)")
    elif ic <= 0:
        reasons.append(f"rank_ic {ic:.4f} is not positive")

    return GateResult(
        passed=not reasons,
        val_accuracy=acc,
        majority_baseline=base,
        rank_ic=ic,
        reasons=reasons,
    )
