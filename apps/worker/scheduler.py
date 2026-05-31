"""Worker-internal scheduler (APScheduler) — drives the self-evolution loop.

Runs the recurring background jobs alongside the live trading loop, but only on
the instance that holds the singleton lock (wired in worker.main), so jobs never
double-run:

  nightly  label_and_evaluate_job — label past signals' realized outcomes from
           the candles table, then evaluate the active champion model on its
           live labeled signals (model_evaluations row).
  weekly   train_and_propose_job  — train a fresh candidate version, evaluate it
           on its training holdout, and *propose* a promotion (pending). Nothing
           auto-deploys: a human approves via POST /models/promotions/{id}/approve.

The job functions are plain async (no APScheduler dependency) so they're unit-
testable directly; `build_scheduler` lazy-imports APScheduler and registers them.

NOTE (MVP honesty): a freshly trained candidate has no *live* signals yet, so its
proposal metric is training-holdout accuracy while the incumbent's is live
directional accuracy. The rationale records both and a human makes the call —
this is exactly the human-approval gate that was chosen.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from config import settings
from db.connection import AsyncSessionLocal

logger = logging.getLogger(__name__)

_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api"))


def resolve_asset_classes(default: list[str]) -> list[str]:
    raw = (settings.self_evolve_asset_classes or "").strip()
    if raw:
        return [a.strip() for a in raw.split(",") if a.strip()]
    return list(default)


# ---------------------------------------------------------------------------
# jobs (plain async — directly testable)
# ---------------------------------------------------------------------------

async def label_and_evaluate_job(asset_classes: list[str]) -> None:
    """Nightly: label realized outcomes, then evaluate the champion per class."""
    from ml.evaluation import evaluate_model
    from ml.labeling import label_outcomes
    from ml.promotion import get_champion_version

    async with AsyncSessionLocal() as session:
        for ac in asset_classes:
            try:
                labeled = await label_outcomes(session, ac)
                version = await get_champion_version(session, ac) or settings.model_version
                await evaluate_model(session, ac, version)
                logger.info("[scheduler] %s: labeled %d, evaluated %s", ac, labeled, version)
            except Exception:
                logger.exception("[scheduler] label/evaluate failed for %s", ac)
        await session.commit()


async def train_and_propose_job(
    asset_classes: list[str],
    *,
    trainer: Optional[Callable[[str, str], Optional[dict]]] = None,
) -> None:
    """Weekly: train a candidate, evaluate on holdout, propose a promotion."""
    train = trainer or _default_trainer
    version = f"cand-{datetime.now(timezone.utc):%Y%m%d}"

    async with AsyncSessionLocal() as session:
        for ac in asset_classes:
            try:
                await _train_candidate_and_propose(session, ac, version, train)
            except Exception:
                logger.exception("[scheduler] train/propose failed for %s", ac)
        await session.commit()


async def _train_candidate_and_propose(session, asset_class: str, version: str,
                                       trainer: Callable[[str, str], Optional[dict]]) -> None:
    from db.models import ModelEvaluation
    from ml.promotion import propose_promotion

    loop = asyncio.get_event_loop()
    metrics = await loop.run_in_executor(None, lambda: trainer(asset_class, version))
    if not metrics:
        logger.info("[scheduler] %s: candidate %s training unavailable — skipped", asset_class, version)
        return

    # Holdout evaluation row for the candidate (directional_accuracy proxied by
    # holdout val accuracy; clearly labeled in metrics/notes).
    session.add(ModelEvaluation(
        asset_class=asset_class, model_type="ensemble", model_version=version,
        n_samples=int(metrics.get("n_val", metrics.get("n_samples", 0)) or 0),
        directional_accuracy=metrics.get("val_accuracy"),
        signal_accuracy=metrics.get("val_accuracy"),
        metrics={**metrics, "source": "training_holdout"},
        notes="holdout evaluation (candidate has no live signals yet)",
    ))
    await session.flush()
    promo = await propose_promotion(session, asset_class, version)
    if promo is not None:
        logger.info("[scheduler] %s: proposed promotion → %s (pending approval)", asset_class, version)


def _default_trainer(asset_class: str, version: str) -> Optional[dict]:
    """Train an ensemble candidate in-process; return its model-card metrics.

    Best-effort + heavy (loads xgboost/sklearn) — only the weekly job calls it,
    and the whole job is exception-guarded. Returns None if training can't run."""
    try:
        import importlib.util

        path = os.path.join(_API_DIR, "scripts", "train_models.py")
        spec = importlib.util.spec_from_file_location("train_models", path)
        tm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tm)  # type: ignore[union-attr]

        symbols, timeframe = tm._defaults_for(asset_class)
        X, y = tm.build_training_set(symbols, asset_class, timeframe)
        out_path = tm.train_ensemble(X, y, asset_class=asset_class, version=version,
                                     symbols=symbols, timeframe=timeframe, threshold=0.005)
        card_path = f"{out_path[:-4]}.card.json"
        with open(card_path) as fh:
            card = json.load(fh)
        return card.get("metrics", {})
    except Exception:
        logger.warning("[scheduler] in-process training failed for %s", asset_class, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# APScheduler wiring (lazy import)
# ---------------------------------------------------------------------------

def build_scheduler(asset_classes: list[str]):
    """Build an AsyncIOScheduler with the self-evolution jobs. Lazy-imports
    APScheduler so importing this module never requires it."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    classes = resolve_asset_classes(asset_classes)
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        label_and_evaluate_job, "interval",
        hours=settings.label_interval_hours, args=[classes],
        id="label_and_evaluate", next_run_time=None,
    )
    scheduler.add_job(
        train_and_propose_job, "interval",
        hours=settings.train_interval_hours, args=[classes],
        id="train_and_propose", next_run_time=None,
    )
    logger.info("[scheduler] built with jobs for %s (label=%dh, train=%dh)",
                classes, settings.label_interval_hours, settings.train_interval_hours)
    return scheduler
