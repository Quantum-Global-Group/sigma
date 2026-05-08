"""LangExtract sentiment — uses the `langextract` Python package.

Body ported from razorBill `nlp.py::LangExtractClient`. By default points
at a local Ollama server (`lx_model_url=http://127.0.0.1:11434`,
`lx_model_id=mistral:7b-instruct`); override `lx_model_url` to use a
hosted langextract endpoint."""

from __future__ import annotations

import logging

from config import settings

from .base import SentimentProvider, SentimentResult

logger = logging.getLogger(__name__)


class LangExtractProvider(SentimentProvider):
    name = "langextract"

    def __init__(self) -> None:
        self.model_id = settings.lx_model_id
        self.model_url = settings.lx_model_url
        self.api_key = settings.langextract_api_key  # ignored for local Ollama

    def score(self, headlines: list[str]) -> SentimentResult:
        if not headlines:
            return SentimentResult(0.0, 0)

        try:
            import langextract as lx  # type: ignore
        except ImportError:
            logger.warning("langextract not installed — returning neutral sentiment")
            return SentimentResult(0.0, 0)

        prompt = (
            "Classify sentiment of each text as negative (-1), neutral (0), "
            "or positive (+1). Return the average as a single numeric value."
        )
        try:
            result = lx.extract(
                text_or_documents=headlines,
                prompt_description=prompt,
                examples=[],
                model_id=self.model_id,
                model_url=self.model_url,
                fence_output=False,
                use_schema_constraints=False,
            )
            score = float(result) if isinstance(result, (int, float)) else 0.0
        except Exception as exc:
            logger.warning("LangExtract sentiment failed: %s", exc)
            return SentimentResult(0.0, 0)

        return SentimentResult(round(score, 4), len(headlines))
