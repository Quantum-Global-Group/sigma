"""Tests for the razorBill-derived strategy package."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.strategies import (
    BreakoutStrategy,
    MeanReversionStrategy,
    MLStrategy,
    MomentumStrategy,
    RegimeStrategy,
    Signal,
    StrategyCombiner,
    build_default_combiner,
    combine_to_result,
)


def _ohlcv_with_features(n: int = 60, trend: float = 0.0):
    rng = np.random.default_rng(0)
    rets = rng.normal(trend, 0.001, n)
    closes = 100 * np.exp(np.cumsum(rets))
    df = pd.DataFrame({
        "o": closes * (1 + rng.normal(0, 0.0005, n)),
        "h": closes * (1 + rng.uniform(0, 0.002, n)),
        "l": closes * (1 - rng.uniform(0, 0.002, n)),
        "c": closes,
        "v": rng.uniform(1e6, 5e6, n),
        "ema_fast": closes,
        "ema_slow": closes,
        "rsi": np.full(n, 50.0),
        "vol_realized": np.full(n, 0.01),
    })
    return df, float(closes[-1])


def test_momentum_signal_shape():
    df, px = _ohlcv_with_features(60, trend=0.001)
    sig = MomentumStrategy().generate_signal("BTC-USD", df, px)
    assert isinstance(sig, Signal)
    assert -1.0 <= sig.strength <= 1.0
    assert 0.0 <= sig.confidence <= 1.0
    assert sig.method == "momentum"


def test_mean_reversion_emits_zero_when_neutral():
    df, px = _ohlcv_with_features(60)
    sig = MeanReversionStrategy().generate_signal("BTC-USD", df, px)
    assert sig.method == "mean_reversion"
    # neutral RSI + no BB excursion → 0
    assert sig.strength == 0.0


def test_breakout_detects_resistance_break():
    df, _ = _ohlcv_with_features(60)
    px = float(df["h"].max() * 1.05)  # 5% above resistance
    sig = BreakoutStrategy().generate_signal("BTC-USD", df, px)
    assert sig.strength == 1.0
    assert sig.confidence > 0


def test_regime_neutral_when_emas_aligned():
    df, px = _ohlcv_with_features(60)
    sig = RegimeStrategy().generate_signal("BTC-USD", df, px)
    assert sig.method == "regime"
    # ema_fast == ema_slow → neutral
    assert sig.strength == 0.0


def test_ml_strategy_uses_external_score():
    df, px = _ohlcv_with_features(60)
    s = MLStrategy({"BTC-USD": 0.05})
    sig = s.generate_signal("BTC-USD", df, px)
    assert sig.strength > 0
    # Strength capped at +1 (score=0.05 × 10 = 0.5)
    assert sig.strength <= 1.0


def test_ml_strategy_unknown_symbol_returns_zero():
    df, px = _ohlcv_with_features(60)
    sig = MLStrategy({}).generate_signal("BTC-USD", df, px)
    assert sig.strength == 0.0
    assert sig.confidence == 0.0


def test_combiner_weights_normalize_and_combine():
    df, px = _ohlcv_with_features(60)
    combiner = StrategyCombiner(
        strategies={
            "momentum": MomentumStrategy(),
            "regime": RegimeStrategy(),
        },
        weights={"momentum": 0.7, "regime": 0.3},
    )
    combined = combiner.combine_signals("BTC-USD", df, px)
    assert combined.method == "combined"
    assert -1.0 <= combined.strength <= 1.0


def test_build_default_combiner_uses_settings():
    combiner = build_default_combiner()
    assert "momentum" in combiner.strategies
    assert abs(sum(combiner.weights.values()) - 1.0) < 1e-6


def test_combine_to_result_translates_signal():
    sig = Signal(strength=0.5, confidence=0.8, method="combined", metadata={"x": 1})
    result = combine_to_result(sig)
    assert result.signal == "BUY"
    assert result.confidence == 0.8
    assert result.component_weights["strength"] == 0.5
    assert result.component_weights["x"] == 1


def test_combine_to_result_holds_in_threshold_band():
    sig = Signal(strength=0.05, confidence=0.5, method="combined")
    assert combine_to_result(sig).signal == "HOLD"
