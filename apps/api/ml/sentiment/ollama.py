"""Ollama-direct sentiment — convenience provider that talks to Ollama's
`/api/generate` endpoint without going through langextract.

razorBill itself drives Ollama via the `langextract` Python package
(see `langextract.py`). This is a sigma-side extension for users who want
Ollama-only without installing langextract. Uses `lx_model_url` and
`lx_model_id` for backward compatibility with razorBill env vars."""

from __future__ import annotations

import logging
import re

from config import settings

from .base import SentimentProvider, SentimentResult

logger = logging.getLogger(__name__)

_PROMPT = (
    "Rate the financial sentiment of the following headline on a scale "
    "from -1 (very negative) to 1 (very positive). Respond with only the "
    "number, no commentary.\n\nHeadline: {headline}\n\nScore:"
)
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


class OllamaProvider(SentimentProvider):
    name = "ollama"

    def __init__(self) -> None:
        self._url = settings.lx_model_url.rstrip("/") + "/api/generate"
        self._model = settings.lx_model_id

    def _score_one(self, headline: str) -> float:
        try:
            import httpx
        except ImportError:
            return 0.0
        try:
            r = httpx.post(
                self._url,
                json={
                    "model": self._model,
                    "prompt": _PROMPT.format(headline=headline),
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
                timeout=20.0,
            )
            r.raise_for_status()
            text = r.json().get("response", "")
        except Exception as exc:
            logger.warning("Ollama call failed: %s", exc)
            return 0.0
        m = _NUM.search(text)
        if not m:
            return 0.0
        try:
            return max(-1.0, min(1.0, float(m.group(0))))
        except ValueError:
            return 0.0

    def score(self, headlines: list[str]) -> SentimentResult:
        if not headlines:
            return SentimentResult(0.0, 0)
        total = sum(self._score_one(h) for h in headlines)
        return SentimentResult(round(total / len(headlines), 4), len(headlines))
