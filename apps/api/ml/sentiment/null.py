from __future__ import annotations

from .base import SentimentProvider, SentimentResult


class NullProvider(SentimentProvider):
    """Returns neutral sentiment. Used when SENTIMENT_PROVIDER=none or when the
    configured provider fails to initialize."""

    name = "null"

    def score(self, headlines: list[str]) -> SentimentResult:
        return SentimentResult(0.0, 0)
