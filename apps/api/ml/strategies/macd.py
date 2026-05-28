"""MACD crossover strategy.

Ported from tradeFlux core/advanced_strategies.py::MACDStrategy, adapted to
sigma's per-symbol Signal contract. Emits a graded strength from the
MACD-histogram (signed distance of the MACD line from its signal line) and
boosts confidence on a fresh crossover at the latest bar."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal


class MacdStrategy(BaseStrategy):
    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> None:
        super().__init__("macd")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        close = features["c"]
        if len(close) < self.slow_period + self.signal_period:
            return Signal(0.0, 0.0, self.name)

        macd = close.ewm(span=self.fast_period).mean() - close.ewm(span=self.slow_period).mean()
        signal_line = macd.ewm(span=self.signal_period).mean()
        hist = macd - signal_line

        h_now = float(hist.iloc[-1])
        h_prev = float(hist.iloc[-2])
        crossed_up = h_prev <= 0 < h_now
        crossed_down = h_prev >= 0 > h_now

        # Graded strength: histogram normalized by price, clipped.
        strength = float(np.clip((h_now / current_price) * 50.0, -1.0, 1.0)) if current_price else 0.0

        # Confidence: magnitude of the histogram move, lifted on a fresh cross.
        confidence = min(1.0, abs(h_now / current_price) * 100.0) if current_price else 0.0
        if crossed_up or crossed_down:
            confidence = min(1.0, confidence + 0.4)

        return Signal(
            strength=strength,
            confidence=float(confidence),
            method=self.name,
            metadata={"macd": h_now, "crossed_up": crossed_up, "crossed_down": crossed_down},
        )
