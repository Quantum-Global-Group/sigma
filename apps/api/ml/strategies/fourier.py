"""Fourier (FFT) cycle-detection strategy.

Ported from tradeFlux core/advanced_strategies.py::FourierTransformStrategy.
Detrends the recent close window, runs an FFT, finds the dominant cycle, and
trades the deviation of price from a cycle-length moving average — adapted to
emit a single graded Signal for the latest bar."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal as sp_signal
from scipy.fft import fft

from .base import BaseStrategy, Signal


class FourierStrategy(BaseStrategy):
    def __init__(self, lookback_period: int = 64, dominant_cycles: int = 3, sensitivity: float = 0.5) -> None:
        super().__init__("fourier")
        self.lookback_period = lookback_period
        self.dominant_cycles = dominant_cycles
        self.sensitivity = sensitivity

    def _dominant_cycles(self, prices: pd.Series) -> list[int]:
        detrended = sp_signal.detrend(prices.values)
        power = np.abs(fft(detrended)) ** 2
        top = np.argsort(power)[::-1][1 : self.dominant_cycles + 1]
        periods = [len(prices) // idx if idx != 0 else float("inf") for idx in top]
        return [int(p) for p in periods if p > 5 and not np.isinf(p)]

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        close = features["c"]
        if len(close) < self.lookback_period:
            return Signal(0.0, 0.0, self.name)

        window = close.iloc[-self.lookback_period:]
        cycles = self._dominant_cycles(window)
        if not cycles:
            return Signal(0.0, 0.0, self.name)

        cycle = min(cycles)
        if cycle <= 0 or cycle >= len(window):
            return Signal(0.0, 0.0, self.name)

        cycle_ma = float(window.rolling(window=cycle).mean().iloc[-1])
        if not np.isfinite(cycle_ma) or cycle_ma <= 0:
            return Signal(0.0, 0.0, self.name)

        prev = float(window.iloc[-2])
        band = self.sensitivity * 0.01
        deviation = (current_price - cycle_ma) / cycle_ma

        strength = 0.0
        # Below cyclic mean + turning up → buy; above + turning down → sell.
        if current_price < cycle_ma * (1 - band) and current_price > prev:
            strength = float(np.clip(-deviation * 10.0, 0.0, 1.0))
        elif current_price > cycle_ma * (1 + band) and current_price < prev:
            strength = float(np.clip(-deviation * 10.0, -1.0, 0.0))

        confidence = min(1.0, abs(deviation) * 8.0)
        return Signal(
            strength=strength,
            confidence=float(confidence),
            method=self.name,
            metadata={"cycle": cycle, "cycle_ma": cycle_ma, "deviation": deviation},
        )
