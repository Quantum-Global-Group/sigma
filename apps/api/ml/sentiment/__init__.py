"""Sentiment providers — pluggable behind a single `score_headlines` API.

Selected by `settings.sentiment_provider`:
  finbert     - HuggingFace ProsusAI/finbert (razorBill canonical)
  langextract - razorBill canonical, uses the `langextract` package against
                a local Ollama or a hosted endpoint (lx_model_url)
  ollama      - direct Ollama HTTP (sigma extension, doesn't need langextract)
  hybrid      - average of finbert + langextract + ollama (any that load)
  none        - neutral

Existing call sites (`from ml.sentiment import score_headlines`) continue
to work unchanged."""

from __future__ import annotations

import logging
from typing import Optional

from config import settings

from .base import SentimentProvider, SentimentResult

logger = logging.getLogger(__name__)

_provider: Optional[SentimentProvider] = None


def _build_provider() -> SentimentProvider:
    name = (settings.sentiment_provider or "finbert").lower()
    if name in ("none", ""):
        from .null import NullProvider
        return NullProvider()
    if name == "finbert":
        from .finbert import FinBertProvider
        return FinBertProvider()
    if name == "langextract":
        from .langextract import LangExtractProvider
        return LangExtractProvider()
    if name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider()
    if name == "hybrid":
        from .hybrid import HybridProvider
        return HybridProvider()
    raise ValueError(f"Unknown sentiment_provider: {name!r}")


def get_provider() -> SentimentProvider:
    global _provider
    if _provider is None:
        try:
            _provider = _build_provider()
        except Exception as exc:
            logger.warning("Sentiment provider init failed: %s — using null", exc)
            from .null import NullProvider
            _provider = NullProvider()
    return _provider


def score_headlines(headlines: list[str]) -> float:
    """Back-compat shim — returns the aggregate score in [-1, 1]."""
    if not headlines:
        return 0.0
    try:
        return get_provider().score(headlines).score
    except Exception as exc:
        logger.warning("Sentiment score failed: %s", exc)
        return 0.0


__all__ = ["SentimentProvider", "SentimentResult", "score_headlines", "get_provider"]
