from __future__ import annotations

import pandas as pd

from .base import BaseStrategy, Signal


class BreakoutStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("breakout")
        self.lookback_period = 20
        self.volume_threshold = 1.5
        self.volatility_expansion_threshold = 1.2

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        if len(features) < self.lookback_period:
            return Signal(0.0, 0.0, self.name)

        last = features.iloc[-1]
        lookback = features.tail(self.lookback_period)
        resistance = float(lookback["h"].max())
        support = float(lookback["l"].min())

        signal = 0.0
        conf = 0.0
        if current_price > resistance and resistance > 0:
            signal = 1.0
            conf = min(1.0, (current_price - resistance) / resistance)
        elif current_price < support and support > 0:
            signal = -1.0
            conf = min(1.0, (support - current_price) / support)

        if signal == 0:
            return Signal(0.0, 0.0, self.name)

        volume_confirmed = True
        if "v" in features.columns and len(features) >= 20:
            avg_vol = features["v"].tail(20).mean()
            cur_vol = features["v"].iloc[-1]
            volume_confirmed = (cur_vol / avg_vol if avg_vol > 0 else 1.0) >= self.volume_threshold
            if not volume_confirmed:
                conf *= 0.6

        vol_expansion = False
        if "vol_realized" in features.columns and len(features) >= 20:
            avg_vol_r = features["vol_realized"].tail(20).mean()
            cur_vol_r = float(last["vol_realized"])
            vol_expansion = cur_vol_r >= avg_vol_r * self.volatility_expansion_threshold
            if vol_expansion:
                conf = min(1.0, conf * 1.2)

        return Signal(
            strength=float(signal),
            confidence=float(conf),
            method=self.name,
            metadata={
                "resistance": resistance,
                "support": support,
                "volume_confirmed": volume_confirmed,
                "volatility_expansion": vol_expansion,
            },
        )
