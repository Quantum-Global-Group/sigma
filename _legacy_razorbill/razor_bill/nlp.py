from __future__ import annotations

from dataclasses import dataclass
from typing import List
import asyncio

from loguru import logger
from .config import settings


@dataclass
class SentimentResult:
    score: float  # -1 to 1
    n_docs: int


async def _fetch_symbol_headlines(symbol: str) -> list[str]:
    # TODO: Integrate a real news/RSS source. Empty list => neutral sentiment.
    return []


class LangExtractClient:
    def __init__(self, model_id: str, model_url: str, api_key: str | None = None) -> None:
        self.model_id = model_id
        self.model_url = model_url
        self.api_key = api_key  # optional for cloud; ignored for local Ollama

    async def fetch_sentiment(self, symbol: str) -> SentimentResult:
        try:
            import langextract as lx  # type: ignore
        except Exception:
            logger.warning("langextract not installed; returning neutral sentiment.")
            return SentimentResult(score=0.0, n_docs=0)

        texts = await _fetch_symbol_headlines(symbol)
        if not texts:
            return SentimentResult(score=0.0, n_docs=0)

        prompt = (
            "Classify sentiment of each text as negative (-1), neutral (0), or positive (+1). "
            "Return the average as a single numeric value."
        )
        try:
            result = lx.extract(
                text_or_documents=texts,
                prompt_description=prompt,
                examples=[],
                model_id=self.model_id,
                model_url=self.model_url,
                fence_output=False,
                use_schema_constraints=False,
            )
            score = float(result) if isinstance(result, (float, int)) else 0.0
            return SentimentResult(score=score, n_docs=len(texts))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"LangExtract sentiment failed: {e}")
            return SentimentResult(score=0.0, n_docs=0)


class FinBertClient:
    def __init__(self) -> None:
        self._tokenizer = None
        self._model = None

    def _ensure_model(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return
        try:
            from transformers import (  # type: ignore
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("transformers is required for FinBERT sentiment") from e
        self._tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
        self._model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
        self._model.eval()

    def _score_batch(self, texts: list[str]) -> list[float]:
        import torch  # type: ignore
        assert self._tokenizer is not None and self._model is not None
        with torch.no_grad():
            inputs = self._tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=256)
            logits = self._model(**inputs).logits
            probs = logits.softmax(dim=1)
            # FinBERT labels: 0 negative, 1 neutral, 2 positive
            weights = torch.tensor([-1.0, 0.0, 1.0])
            scores = (probs * weights).sum(dim=1)
            return scores.cpu().numpy().tolist()

    async def fetch_sentiment(self, symbol: str) -> SentimentResult:
        texts = await _fetch_symbol_headlines(symbol)
        if not texts:
            return SentimentResult(score=0.0, n_docs=0)
        self._ensure_model()
        batch_size = 16
        all_scores: list[float] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            all_scores.extend(self._score_batch(batch))
        if not all_scores:
            return SentimentResult(score=0.0, n_docs=0)

        avg = sum(all_scores) / len(all_scores)
        return SentimentResult(score=avg, n_docs=len(texts))


def get_sentiment_client():
    provider = (settings.sentiment_provider or "none").lower()
    if provider == "langextract":
        return LangExtractClient(
            model_id=settings.lx_model_id,
            model_url=settings.lx_model_url,
            api_key=settings.langextract_api_key,  # ignored for local
        )
    if provider == "finbert":
        try:
            return FinBertClient()
        except Exception as e:  # noqa: BLE001
            logger.warning("FinBERT unavailable ({}); falling back to LangExtract.", e)
            return LangExtractClient(settings.lx_model_id, settings.lx_model_url, None)
    if provider == "hybrid":
        try:
            return FinBertClient()
        except Exception:
            return LangExtractClient(settings.lx_model_id, settings.lx_model_url, settings.langextract_api_key)
    return LangExtractClient(settings.lx_model_id, settings.lx_model_url, None)