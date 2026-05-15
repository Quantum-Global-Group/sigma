from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Signal:
    """Strategy-level signal — strength in [-1, 1], confidence in [0, 1]."""

    strength: float
    confidence: float
    method: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float,
    ) -> Signal:
        """Produce a `Signal` for the given symbol/features/price."""

    def should_trade(self, signal: Signal, min_confidence: float = 0.3) -> bool:
        return abs(signal.strength) > 0.1 and signal.confidence >= min_confidence
