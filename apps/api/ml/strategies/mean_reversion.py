from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("mean_reversion")
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.bb_period = 20
        self.bb_std = 2.0

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        if len(features) < self.bb_period:
            return Signal(0.0, 0.0, self.name)

        last = features.iloc[-1]

        rsi_signal = 0.0
        rsi_conf = 0.0
        if "rsi" in features.columns:
            rsi = float(last["rsi"])
            if rsi < self.rsi_oversold:
                rsi_signal = 1.0
                rsi_conf = (self.rsi_oversold - rsi) / self.rsi_oversold
            elif rsi > self.rsi_overbought:
                rsi_signal = -1.0
                rsi_conf = (rsi - self.rsi_overbought) / (100 - self.rsi_overbought)

        bb_signal = 0.0
        bb_conf = 0.0
        prices = features["c"].tail(self.bb_period)
        sma = float(prices.mean())
        std = float(prices.std())
        upper = sma + self.bb_std * std
        lower = sma - self.bb_std * std
        if current_price < lower and (lower - sma) > 0:
            bb_signal = 1.0
            bb_conf = min(1.0, (lower - current_price) / (lower - sma))
        elif current_price > upper and (upper - sma) > 0:
            bb_signal = -1.0
            bb_conf = min(1.0, (current_price - upper) / (upper - sma))

        if rsi_signal == 0 and bb_signal == 0:
            return Signal(0.0, 0.0, self.name)

        if rsi_signal != 0 and bb_signal != 0:
            if np.sign(rsi_signal) == np.sign(bb_signal):
                strength = (rsi_signal + bb_signal) / 2.0
                conf = (rsi_conf + bb_conf) / 2.0
            elif rsi_conf > bb_conf:
                strength, conf = rsi_signal, rsi_conf * 0.5
            else:
                strength, conf = bb_signal, bb_conf * 0.5
        elif rsi_signal != 0:
            strength, conf = rsi_signal, rsi_conf
        else:
            strength, conf = bb_signal, bb_conf

        return Signal(
            strength=float(strength),
            confidence=float(conf),
            method=self.name,
            metadata={
                "rsi": float(last.get("rsi", 50.0)),
                "bb_signal": bb_signal,
                "rsi_signal": rsi_signal,
            },
        )
