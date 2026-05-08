"""Inference layer — registry-driven model loading.

Resolves a model artifact via `ml.models.registry` keyed by asset class. If no
artifact loads, falls back to a transparent rule-based heuristic so the API
never errors purely from a missing model file."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


class SignalResult:
    def __init__(
        self,
        signal: str,
        confidence: float,
        predicted_return: float,
        component_weights: Optional[dict] = None,
    ):
        self.signal = signal
        self.confidence = confidence
        self.predicted_return = predicted_return
        self.model_version = settings.model_version
        self.component_weights = component_weights


def _heuristic_predict(features: pd.DataFrame) -> SignalResult:
    """Fallback rule-based signal: RSI + EMA + 5-day momentum."""
    if features.empty:
        return SignalResult("HOLD", 0.5, 0.0, {"heuristic": 1.0})

    row = features.iloc[-1]
    rsi = row.get("rsi_14", 50.0)
    ema_ratio = row.get("ema_ratio", 1.0)
    ret_5d = row.get("ret_5d", 0.0)

    score = 0.0
    score += (50 - rsi) / 50 * 0.4
    score += (ema_ratio - 1.0) * 2.0 * 0.4
    score += np.clip(ret_5d * 5, -0.2, 0.2)

    confidence = float(np.clip(abs(score) * 1.5 + 0.35, 0.35, 0.95))
    predicted_return = float(np.clip(score * 0.05, -0.10, 0.10))

    if score > 0.15:
        signal = "BUY"
    elif score < -0.15:
        signal = "SELL"
    else:
        signal = "HOLD"

    return SignalResult(
        signal,
        round(confidence, 4),
        round(predicted_return, 6),
        {"heuristic": 1.0},
    )


def predict(features: pd.DataFrame, *, asset_class: str = "equity") -> SignalResult:
    # Local import to avoid a circular dep: ml.models.base re-exports SignalResult.
    from ml.models.registry import resolve

    model = resolve(asset_class)
    if model is not None:
        try:
            return model.predict(features)
        except Exception as exc:
            logger.warning("Trained model predict failed: %s — using heuristic", exc)
    return _heuristic_predict(features)
