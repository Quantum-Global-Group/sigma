"""
FinBERT financial sentiment scoring.

Wraps `ProsusAI/finbert` from HuggingFace. Lazy-loaded so the ~440MB model
weights are only fetched when sentiment is actually requested. Returns 0.0
(neutral) when the model is unavailable so callers don't need to special-case.
"""

from __future__ import annotations

import logging

from config import settings

logger = logging.getLogger(__name__)

_pipeline = None


def load_finbert():
    """Lazy-load the FinBERT pipeline. Returns None on failure."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    try:
        from transformers import pipeline as hf_pipeline  # type: ignore
        kwargs: dict = {"model": "ProsusAI/finbert"}
        if settings.huggingface_token:
            kwargs["token"] = settings.huggingface_token
        _pipeline = hf_pipeline("text-classification", **kwargs)
        return _pipeline
    except Exception as exc:
        logger.warning("FinBERT load failed: %s — sentiment will return 0.0", exc)
        _pipeline = False  # sentinel for "tried and failed"
        return None


def score_headlines(headlines: list[str]) -> float:
    """Aggregate sentiment for a list of headlines.

    Returns a score in [-1, 1] where +1 = strongly positive, -1 = strongly negative.
    """
    if not headlines:
        return 0.0

    pipe = load_finbert()
    if pipe is None or pipe is False:
        return 0.0

    try:
        results = pipe(headlines, truncation=True)
    except Exception as exc:
        logger.warning("FinBERT inference failed: %s", exc)
        return 0.0

    score = 0.0
    for r in results:
        label = r["label"].lower()
        s = float(r["score"])
        if label == "positive":
            score += s
        elif label == "negative":
            score -= s
        # 'neutral' contributes 0
    return round(score / len(results), 4)
