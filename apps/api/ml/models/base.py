"""
Abstract interface for SIGMA signal models.

All trainable models implement train/predict/save/load. Predict returns a
SignalResult so the inference pipeline doesn't need to special-case model types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from ml.inference import SignalResult


class BaseSignalModel(ABC):
    """Common interface for any model that predicts BUY/SELL/HOLD signals."""

    model_version: str = "v1.0"

    @abstractmethod
    def train(self, X: pd.DataFrame, y: np.ndarray) -> None:
        """Train on feature DataFrame X and integer label vector y (0=SELL, 1=HOLD, 2=BUY)."""

    @abstractmethod
    def predict(self, features: pd.DataFrame) -> SignalResult:
        """Predict on the latest row of features. Returns a SignalResult."""

    @abstractmethod
    def save(self, path: str) -> None:
        """Persist model weights/state to disk."""

    @classmethod
    @abstractmethod
    def load(cls, path: str) -> "BaseSignalModel":
        """Load a previously-saved model from disk."""


def label_signals(returns: pd.Series, threshold: float = 0.005) -> np.ndarray:
    """Map a future return series to integer labels (0=SELL, 1=HOLD, 2=BUY).

    The signal model is trained to predict the next-day classification:
      future_return > +threshold → BUY (2)
      future_return < -threshold → SELL (0)
      otherwise              → HOLD (1)
    """
    labels = np.full(len(returns), 1, dtype=int)
    labels[returns.values > threshold] = 2
    labels[returns.values < -threshold] = 0
    return labels


def label_to_signal(label: int) -> str:
    return {0: "SELL", 1: "HOLD", 2: "BUY"}[int(label)]
