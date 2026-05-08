"""FinBERT (`ProsusAI/finbert`) — lazy-loaded HuggingFace pipeline."""

from __future__ import annotations

import logging

from config import settings

from .base import SentimentProvider, SentimentResult

logger = logging.getLogger(__name__)


class FinBertProvider(SentimentProvider):
    name = "finbert"

    def __init__(self) -> None:
        self._pipeline = None
        self._tried = False

    def _load(self):
        if self._tried:
            return self._pipeline
        self._tried = True
        try:
            from transformers import pipeline as hf_pipeline  # type: ignore
            kwargs: dict = {"model": "ProsusAI/finbert"}
            if settings.huggingface_token:
                kwargs["token"] = settings.huggingface_token
            self._pipeline = hf_pipeline("text-classification", **kwargs)
        except Exception as exc:
            logger.warning("FinBERT load failed: %s", exc)
            self._pipeline = None
        return self._pipeline

    def score(self, headlines: list[str]) -> SentimentResult:
        if not headlines:
            return SentimentResult(0.0, 0)

        pipe = self._load()
        if pipe is None:
            return SentimentResult(0.0, 0)

        try:
            results = pipe(headlines, truncation=True)
        except Exception as exc:
            logger.warning("FinBERT inference failed: %s", exc)
            return SentimentResult(0.0, 0)

        total = 0.0
        for r in results:
            label = r["label"].lower()
            s = float(r["score"])
            if label == "positive":
                total += s
            elif label == "negative":
                total -= s
        return SentimentResult(round(total / len(results), 4), len(results))
