"""
Week-1 inference stub: rule-based signal derived from RSI + EMA ratio.
Replace with trained sklearn/PyTorch model in Week 2 (see ml/models/).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings


class SignalResult:
    def __init__(self, signal: str, confidence: float, predicted_return: float):
        self.signal = signal
        self.confidence = confidence
        self.predicted_return = predicted_return
        self.model_version = settings.model_version


def predict(features: pd.DataFrame) -> SignalResult:
    if features.empty:
        return SignalResult("HOLD", 0.5, 0.0)

    row = features.iloc[-1]
    rsi = row.get("rsi_14", 50.0)
    ema_ratio = row.get("ema_ratio", 1.0)
    bb_width = row.get("bb_width", 0.05)
    ret_5d = row.get("ret_5d", 0.0)

    # Simple heuristic score → signal
    score = 0.0
    score += (50 - rsi) / 50 * 0.4          # oversold bias toward BUY
    score += (ema_ratio - 1.0) * 2.0 * 0.4   # uptrend bias toward BUY
    score += np.clip(ret_5d * 5, -0.2, 0.2)  # recent momentum

    confidence = float(np.clip(abs(score) * 1.5 + 0.35, 0.35, 0.95))
    predicted_return = float(np.clip(score * 0.05, -0.10, 0.10))

    if score > 0.15:
        signal = "BUY"
    elif score < -0.15:
        signal = "SELL"
    else:
        signal = "HOLD"

    return SignalResult(signal, round(confidence, 4), round(predicted_return, 6))
