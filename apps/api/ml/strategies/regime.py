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

        # Regime is determined by EMA direction alone. The original code gated bear
        # on vol_realized > 0.05, but vol_realized is rolling std of 1-bar returns
        # (forex 4h: ~0.001-0.003; equity daily: ~0.01-0.02) — the 0.05 threshold
        # is never reached, making bear physically unreachable and removing all SELL
        # signals from the regime strategy across every asset class.
        # vol_realized still boosts confidence when markets are actively moving.
        if ema_fast > ema_slow:
            regime, strength, conf = "bull", 1.0, 0.7
        elif ema_fast < ema_slow:
            regime, strength, conf = "bear", -1.0, 0.7
        else:
            regime, strength, conf = "neutral", 0.0, 0.3

        trend_strength = abs(ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0.0
        # Scale vol_realized to a useful [0,1] range: typical values are
        # 0.001-0.003 (forex 4h) and 0.01-0.02 (equity daily), so divide by 0.03.
        vol_contribution = min(1.0, vol_realized / 0.03)
        conf = min(1.0, conf + trend_strength * 0.5 + vol_contribution * 0.1)

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
