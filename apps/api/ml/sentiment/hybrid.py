"""Hybrid sentiment — average of any providers that successfully load.

Useful when you want FinBERT's calibrated probabilities combined with an LLM
narrative score. Skips providers that raise / return no docs."""

from __future__ import annotations

from .base import SentimentProvider, SentimentResult


class HybridProvider(SentimentProvider):
    name = "hybrid"

    def __init__(self) -> None:
        from .finbert import FinBertProvider
        from .langextract import LangExtractProvider
        from .ollama import OllamaProvider

        self._providers: list[SentimentProvider] = [
            FinBertProvider(),
            LangExtractProvider(),
            OllamaProvider(),
        ]

    def score(self, headlines: list[str]) -> SentimentResult:
        if not headlines:
            return SentimentResult(0.0, 0)

        scores: list[float] = []
        for p in self._providers:
            try:
                r = p.score(headlines)
            except Exception:
                continue
            if r.n_docs > 0:
                scores.append(r.score)

        if not scores:
            return SentimentResult(0.0, 0)
        return SentimentResult(round(sum(scores) / len(scores), 4), len(headlines))
