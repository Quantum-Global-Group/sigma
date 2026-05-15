from __future__ import annotations

import pandas as pd

from .base import BaseStrategy, Signal


class RegimeStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("regime")

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        if len(features) < 26:
            return Signal(0.0, 0.0, self.name)

        last = features.iloc[-1]
        ema_fast = float(last.get("ema_fast", current_price))
        ema_slow = float(last.get("ema_slow", current_price))
        vol_realized = float(last.get("vol_realized", 0.0))

        if ema_fast > ema_slow and vol_realized < 0.05:
            regime, strength, conf = "bull", 1.0, 0.7
        elif ema_fast < ema_slow and vol_realized > 0.05:
            regime, strength, conf = "bear", -1.0, 0.7
        else:
            regime, strength, conf = "neutral", 0.0, 0.3

        trend_strength = abs(ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0.0
        conf = min(1.0, conf + trend_strength)

        return Signal(
            strength=float(strength),
            confidence=float(conf),
            method=self.name,
            metadata={
                "regime": regime,
                "trend_strength": trend_strength,
                "volatility": vol_realized,
            },
        )
