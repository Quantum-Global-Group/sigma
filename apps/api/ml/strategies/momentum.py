from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("momentum")
        self.momentum_periods = [1, 3, 5, 10, 20]
        self.volume_confirmation = True
        self.min_volume_spike = 1.5

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        if len(features) < max(self.momentum_periods):
            return Signal(0.0, 0.0, self.name)

        last = features.iloc[-1]
        scores: list[float] = []
        for period in self.momentum_periods:
            if len(features) >= period:
                scores.append(features["c"].iloc[-1] / features["c"].iloc[-period] - 1.0)
        if not scores:
            return Signal(0.0, 0.0, self.name)

        weights = np.array([1.0 / (i + 1) for i in range(len(scores))])
        weights /= weights.sum()
        momentum_score = float(np.average(scores, weights=weights))

        volume_confirmed = True
        if self.volume_confirmation and "v" in features.columns and len(features) >= 20:
            avg_vol = features["v"].tail(20).mean()
            cur_vol = features["v"].iloc[-1]
            volume_confirmed = (cur_vol / avg_vol if avg_vol > 0 else 1.0) >= self.min_volume_spike

        trend_strength = 0.0
        if "ema_fast" in features.columns and "ema_slow" in features.columns:
            ema_fast = float(last["ema_fast"])
            ema_slow = float(last["ema_slow"])
            if ema_slow > 0:
                trend_strength = float(np.clip((ema_fast - ema_slow) / ema_slow, -1.0, 1.0))

        signal_strength = float(np.clip(momentum_score * 10.0, -1.0, 1.0))
        if signal_strength > 0 and trend_strength > 0:
            signal_strength *= 1.0 + trend_strength
        elif signal_strength < 0 and trend_strength < 0:
            signal_strength *= 1.0 + abs(trend_strength)
        signal_strength = float(np.clip(signal_strength, -1.0, 1.0))

        confidence = min(1.0, abs(momentum_score) * 20.0)
        if not volume_confirmed:
            confidence *= 0.7

        return Signal(
            strength=signal_strength,
            confidence=float(confidence),
            method=self.name,
            metadata={
                "momentum_score": momentum_score,
                "trend_strength": trend_strength,
                "volume_confirmed": volume_confirmed,
            },
        )
