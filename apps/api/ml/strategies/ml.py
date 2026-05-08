from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal


class MLStrategy(BaseStrategy):
    """Wraps an externally-supplied per-symbol model score into a Signal.

    The combiner can either pre-load `model_predictions` at construction time
    or pass them at `combine_signals` time."""

    def __init__(self, model_predictions: dict[str, float] | None = None) -> None:
        super().__init__("ml")
        self.model_predictions: dict[str, float] = model_predictions or {}

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        if symbol not in self.model_predictions or len(features) < 50:
            return Signal(0.0, 0.0, self.name)

        score = float(self.model_predictions[symbol])
        last = features.iloc[-1]
        volatility = float(last.get("vol_realized", 0.0))

        if volatility > 0:
            confidence = min(1.0, abs(score) / (volatility + 1e-6))
        else:
            confidence = abs(score)

        strength = float(np.clip(score * 10.0, -1.0, 1.0))
        return Signal(
            strength=strength,
            confidence=float(confidence),
            method=self.name,
            metadata={"model_score": score, "volatility": volatility},
        )
