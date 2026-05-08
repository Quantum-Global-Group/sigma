"""LangExtract sentiment — REST endpoint that returns structured extractions.

Ported from razorBill `nlp.py::LangExtractClient`. Body of the HTTP call lives
here; the razorBill subtree port will adjust the request shape if it has
diverged."""

from __future__ import annotations

import logging
from typing import Optional

from config import settings

from .base import SentimentProvider, SentimentResult

logger = logging.getLogger(__name__)


class LangExtractProvider(SentimentProvider):
    name = "langextract"

    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self._url = api_url or settings.langextract_api_url
        self._key = api_key or settings.langextract_api_key

    def score(self, headlines: list[str]) -> SentimentResult:
        if not headlines or not self._url:
            return SentimentResult(0.0, 0)

        try:
            import httpx
        except ImportError:
            return SentimentResult(0.0, 0)

        try:
            r = httpx.post(
                self._url,
                json={"texts": headlines},
                headers={"Authorization": f"Bearer {self._key}"} if self._key else None,
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning("LangExtract call failed: %s", exc)
            return SentimentResult(0.0, 0)

        # Expect: {"results": [{"sentiment": float in [-1, 1]}, ...]}
        results = data.get("results", [])
        if not results:
            return SentimentResult(0.0, 0)
        total = sum(float(r.get("sentiment", 0.0)) for r in results)
        return SentimentResult(round(total / len(results), 4), len(results))
