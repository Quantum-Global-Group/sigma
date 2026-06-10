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
        min_agreement: int = 0,
        vote_threshold: float = 0.05,
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

        strength   = float(np.clip(total_strength, -1.0, 1.0))
        confidence = float(np.clip(total_confidence, 0.0, 1.0))

        # Agreement filter: count how many strategies vote in the same direction
        # as the combined signal. If fewer than min_agreement agree, collapse to
        # a neutral (strength=0) signal so it resolves to HOLD at the gate.
        if min_agreement > 0 and strength != 0.0:
            direction = 1 if strength > 0 else -1
            votes = sum(
                1 for sig in signals.values()
                if sig.strength * direction > vote_threshold
            )
            metadata_agreement = {"agreement_votes": votes, "agreement_required": min_agreement}
            if votes < min_agreement:
                return Signal(
                    strength=0.0,
                    confidence=confidence * 0.5,   # preserve partial confidence for audit
                    method="combined",
                    metadata={
                        "component_signals": {n: s.strength for n, s in signals.items()},
                        "component_confidence": {n: s.confidence for n, s in signals.items()},
                        **metadata_agreement,
                        "agreement_veto": True,
                    },
                )
        else:
            metadata_agreement = {}

        return Signal(
            strength=strength,
            confidence=confidence,
            method="combined",
            metadata={
                "component_signals": {name: s.strength for name, s in signals.items()},
                "component_confidence": {name: s.confidence for name, s in signals.items()},
                **metadata_agreement,
            },
        )


def _resolve_strategy_config(asset_class: Optional[str]) -> tuple[str, str]:
    """Return (names_csv, weights_csv) for an asset class, falling back to the
    legacy global enabled_strategies / strategy_weights."""
    if asset_class == "crypto" and settings.crypto_strategies.strip():
        return settings.crypto_strategies, settings.crypto_strategy_weights
    if asset_class == "equity" and settings.equity_strategies.strip():
        return settings.equity_strategies, settings.equity_strategy_weights
    if asset_class == "forex" and settings.forex_strategies.strip():
        return settings.forex_strategies, settings.forex_strategy_weights
    return settings.enabled_strategies, settings.strategy_weights


# Strategy parameter overrides for 4h forex bars.
# Default parameters were designed for daily equity bars (dt=1/252).
# 4h bars ≈ 6 bars/day, so multiply daily bar counts by 6 to preserve
# equivalent real-time lookback windows.
_FOREX_4H_PARAMS: dict[str, dict] = {
    "momentum":      {"momentum_periods": [6, 12, 24, 48, 120]},   # 1d/2d/4d/8d/20d
    "mean_reversion": {"bb_period": 48},                            # ~1 week of 4h bars
    "macd":          {"fast_period": 48, "slow_period": 104, "signal_period": 36},
    "fourier":       {"lookback_period": 128},                      # ~3 weeks, catches weekly cycles
}


def build_default_combiner(asset_class: Optional[str] = None) -> StrategyCombiner:
    """Construct a combiner for the given asset class.

    crypto/equity pull their own strategy lists (SDE is equity-only — it
    assumes daily bars). With no asset_class, or an empty per-asset list, this
    falls back to the legacy global enabled_strategies.

    Forex uses 4h bars — strategy parameters are scaled accordingly via
    _FOREX_4H_PARAMS so lookback windows represent the same real-time duration
    as their daily-bar defaults."""
    names_csv, weights_csv = _resolve_strategy_config(asset_class)
    names = [s.strip() for s in names_csv.split(",") if s.strip()]
    raw_weights = [float(w.strip()) for w in weights_csv.split(",") if w.strip()]
    # Empty weights → equal weight across the selected strategies.
    if not raw_weights:
        raw_weights = [1.0] * len(names)
    while len(raw_weights) < len(names):
        raw_weights.append(0.0)
    raw_weights = raw_weights[: len(names)]

    # Forex 4h: apply calibrated parameters instead of daily-bar defaults.
    param_overrides = _FOREX_4H_PARAMS if asset_class == "forex" else {}

    # Phase C: prefer learned per-strategy weights (fit from each strategy's
    # labeled directional hit-rate) when available; else the equal/CSV weights.
    from ml.strategy_weights import load_learned_weights
    learned = load_learned_weights(asset_class)
    use_learned = bool(learned) and any(learned.get(n, 0.0) > 0 for n in names)
    if use_learned:
        logger.info("combiner[%s]: using learned strategy weights", asset_class)

    strategies: dict[str, BaseStrategy] = {}
    weights: dict[str, float] = {}
    for name, w in zip(names, raw_weights):
        factory = _STRATEGY_FACTORIES.get(name)
        if factory is None:
            logger.warning("Unknown strategy %r in strategy config — skipping", name)
            continue
        kwargs = param_overrides.get(name, {})
        try:
            strategies[name] = factory(**kwargs)
        except TypeError:
            strategies[name] = factory()   # fallback if strategy doesn't accept kwargs
        weights[name] = float(learned.get(name, 0.0)) if use_learned else float(w)

    if not strategies:
        # Never break startup: fall back to all registered strategies, equal weight.
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
