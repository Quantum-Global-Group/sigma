"""Multi-strategy signal generation.

Ported from razorBill `strategies.py`. Five concrete strategies plus a
combiner that weights them per `settings.strategy_weights`. Output of
`combine_signals` is a `Signal` dataclass; `combine_to_result` translates
to sigma's `SignalResult` for use inside the inference pipeline."""

from __future__ import annotations

from .base import BaseStrategy, Signal
from .breakout import BreakoutStrategy
from .combiner import StrategyCombiner, build_default_combiner, combine_to_result
from .mean_reversion import MeanReversionStrategy
from .ml import MLStrategy
from .momentum import MomentumStrategy
from .regime import RegimeStrategy

__all__ = [
    "BaseStrategy",
    "Signal",
    "MomentumStrategy",
    "MeanReversionStrategy",
    "BreakoutStrategy",
    "RegimeStrategy",
    "MLStrategy",
    "StrategyCombiner",
    "build_default_combiner",
    "combine_to_result",
]
