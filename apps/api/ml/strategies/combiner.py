"""Strategy combiner — weighted blend of per-strategy signals.

Mirrors razorBill's `StrategyCombiner` and adds two adapters: one to build
a default combiner from `settings.enabled_strategies` / `settings.strategy_weights`,
and one to translate the combined `Signal` into sigma's `SignalResult`."""

from __future__ import annotations

import logging
from typing import Mapping, Optional

import numpy as np
import pandas as pd

from config import settings
from ml.inference import SignalResult

from .base import BaseStrategy, Signal
from .breakout import BreakoutStrategy
from .fourier import FourierStrategy
from .ict import ICTStrategy
from .macd import MacdStrategy
from .mean_reversion import MeanReversionStrategy
from .ml import MLStrategy
from .momentum import MomentumStrategy
from .regime import RegimeStrategy
from .sde import GbmStrategy, HestonVolStrategy, OuMeanReversionStrategy

logger = logging.getLogger(__name__)

_STRATEGY_FACTORIES: dict[str, type[BaseStrategy]] = {
    # razorBill-derived (defaults)
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
    "regime": RegimeStrategy,
    "ml": MLStrategy,
    # tradeFlux-derived (opt in via settings.enabled_strategies)
    "macd": MacdStrategy,
    "fourier": FourierStrategy,
    "gbm": GbmStrategy,
    "ou": OuMeanReversionStrategy,
    "heston": HestonVolStrategy,
    "ict": ICTStrategy,
}


class StrategyCombiner:
    def __init__(
        self,
        strategies: Mapping[str, BaseStrategy],
        weights: Mapping[str, float],
    ) -> None:
        self.strategies = dict(strategies)
        total = sum(weights.values()) or 1.0
        self.weights = {k: v / total for k, v in weights.items()}

    def combine_signals(
        self,
        symbol: str,
        features: pd.DataFrame,
        current_price: float,
        model_predictions: Optional[Mapping[str, float]] = None,
    ) -> Signal:
        signals: dict[str, Signal] = {}
        for name, strategy in self.strategies.items():
            try:
                if isinstance(strategy, MLStrategy) and model_predictions:
                    strategy.model_predictions = dict(model_predictions)
                signals[name] = strategy.generate_signal(symbol, features, current_price)
            except Exception:
                logger.exception("strategy %s failed for %s", name, symbol)

        if not signals:
            return Signal(0.0, 0.0, "combined", metadata={"component_signals": {}})

        total_strength = 0.0
        total_confidence = 0.0
        for name, sig in signals.items():
            w = self.weights.get(name, 0.0)
            total_strength += sig.strength * w
            total_confidence += sig.confidence * w

        return Signal(
            strength=float(np.clip(total_strength, -1.0, 1.0)),
            confidence=float(np.clip(total_confidence, 0.0, 1.0)),
            method="combined",
            metadata={
                "component_signals": {name: s.strength for name, s in signals.items()},
                "component_confidence": {name: s.confidence for name, s in signals.items()},
            },
        )


def build_default_combiner() -> StrategyCombiner:
    """Construct a combiner from settings.enabled_strategies / strategy_weights."""
    names = [s.strip() for s in settings.enabled_strategies.split(",") if s.strip()]
    raw_weights = [float(w.strip()) for w in settings.strategy_weights.split(",") if w.strip()]
    while len(raw_weights) < len(names):
        raw_weights.append(0.0)
    raw_weights = raw_weights[: len(names)]

    strategies: dict[str, BaseStrategy] = {}
    weights: dict[str, float] = {}
    for name, w in zip(names, raw_weights):
        factory = _STRATEGY_FACTORIES.get(name)
        if factory is None:
            logger.warning("Unknown strategy %r in enabled_strategies — skipping", name)
            continue
        strategies[name] = factory()
        weights[name] = float(w)

    if not strategies:
        # Fall back to all-five-equal so the combiner never breaks startup
        for name, factory in _STRATEGY_FACTORIES.items():
            strategies[name] = factory()
            weights[name] = 1.0

    return StrategyCombiner(strategies, weights)


def combine_to_result(combined: Signal, *, model_version: str = "combined-v1") -> SignalResult:
    """Translate a combiner Signal into sigma's SignalResult contract."""
    threshold = 0.1  # razorBill's should_trade lower bound
    if combined.strength > threshold:
        signal = "BUY"
    elif combined.strength < -threshold:
        signal = "SELL"
    else:
        signal = "HOLD"

    component_weights = {
        "strength": combined.strength,
        "confidence": combined.confidence,
        "method": combined.method,
    }
    component_weights.update(combined.metadata or {})

    result = SignalResult(
        signal=signal,
        confidence=float(np.clip(combined.confidence, 0.0, 1.0)),
        predicted_return=float(combined.strength * 0.05),  # rough scaling
        component_weights=component_weights,
    )
    result.model_version = model_version
    return result
