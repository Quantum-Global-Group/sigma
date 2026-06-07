"""Learned strategy weights (Phase C of the modeling overhaul).

Replaces equal-weight blending with weights fit from each strategy's historical
*directional edge* — how often `sign(its vote)` matched `sign(realized_return)`
on non-flat, labeled `signal_history` rows. A strategy's vote is read from the
stored `component_weights["component_signals"]`, so this needs no feature
recompute. Hit-rate is shrunk toward 0.5 for small samples (so a strategy that
rarely fires can't get an extreme weight), and sub-coin-flip strategies fall to
~0 — they stop polluting the blend.

Weights persist as JSON per asset class in `settings.model_dir`
(`strategy_weights_{asset_class}.json`); `build_default_combiner` loads them when
`settings.use_learned_strategy_weights` is on, falling back to equal weights when
there is no measurable edge yet. Fit nightly by the scheduler
(`label_and_evaluate_job`) or on demand via `scripts/fit_strategy_weights.py`.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import SignalHistory

logger = logging.getLogger(__name__)


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _weights_path(asset_class: str) -> Path:
    return Path(settings.model_dir) / f"strategy_weights_{asset_class}.json"


def _as_components(component_weights) -> dict:
    cw = component_weights or {}
    if not isinstance(cw, dict):
        try:
            cw = json.loads(cw)
        except Exception:
            return {}
    comps = cw.get("component_signals") or {}
    return comps if isinstance(comps, dict) else {}


def compute_strategy_weights(
    rows: Sequence,
    *,
    flat_threshold: Optional[float] = None,
    prior_strength: float = 20.0,
    min_total_samples: int = 50,
) -> dict[str, float]:
    """Per-strategy normalized weights from labeled rows. Pure / testable.

    Each row needs `realized_return` and `component_weights` (with the nested
    `component_signals` map). Returns {} when there's too little labeled data
    (< min_total_samples non-flat rows) or no strategy shows positive edge — the
    caller then keeps equal weights rather than trusting noise."""
    flat = settings.label_flat_threshold if flat_threshold is None else flat_threshold
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # strat -> [hits, total]
    n_scored = 0

    for r in rows:
        rr = getattr(r, "realized_return", None)
        if rr is None:
            continue
        rr = float(rr)
        if abs(rr) < flat:
            continue  # flat outcome — no directional signal to score
        n_scored += 1
        for strat, s in _as_components(getattr(r, "component_weights", None)).items():
            if s is None:
                continue
            try:
                s = float(s)
            except (TypeError, ValueError):
                continue
            if abs(s) < 1e-9:
                continue  # strategy abstained on this bar
            stats[strat][1] += 1
            if _sign(s) == _sign(rr):
                stats[strat][0] += 1

    raw: dict[str, float] = {}
    for strat, (hits, total) in stats.items():
        # Shrink the hit-rate toward 0.5 so small samples can't earn big weights.
        hit_rate = (hits + 0.5 * prior_strength) / (total + prior_strength)
        raw[strat] = max(0.0, hit_rate - 0.5)  # predictive edge over a coin flip

    if n_scored < min_total_samples:
        return {}  # too little labeled data — keep equal weights, avoid noise
    norm = sum(raw.values())
    if norm <= 0:
        return {}
    return {k: round(v / norm, 6) for k, v in raw.items()}


async def fit_strategy_weights(session: AsyncSession, asset_class: str) -> dict[str, float]:
    q = (
        select(SignalHistory)
        .where(SignalHistory.asset_class == asset_class)
        .where(SignalHistory.labeled_at.is_not(None))
    )
    rows = list((await session.execute(q)).scalars().all())
    return compute_strategy_weights(rows)


async def fit_and_store(session: AsyncSession, asset_class: str) -> Optional[dict[str, float]]:
    """Fit weights for an asset class and persist them. Returns the weights or None."""
    weights = await fit_strategy_weights(session, asset_class)
    if not weights:
        # Remove any stale weights file so we cleanly revert to equal weights.
        try:
            _weights_path(asset_class).unlink(missing_ok=True)
        except Exception:
            pass
        logger.info("[weights] %s: insufficient labeled data / no edge — keeping equal weights", asset_class)
        return None
    path = _weights_path(asset_class)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(weights, indent=2, sort_keys=True))
    logger.info("[weights] %s: wrote learned weights %s", asset_class, weights)
    return weights


def load_learned_weights(asset_class: Optional[str]) -> Optional[dict[str, float]]:
    """Load persisted learned weights, or None (caller falls back to equal/CSV).

    Gated by settings.use_learned_strategy_weights so it can be disabled."""
    if not asset_class or not settings.use_learned_strategy_weights:
        return None
    try:
        path = _weights_path(asset_class)
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict) and data:
                return {k: float(v) for k, v in data.items()}
    except Exception:
        logger.warning("[weights] failed to load learned weights for %s", asset_class, exc_info=True)
    return None
