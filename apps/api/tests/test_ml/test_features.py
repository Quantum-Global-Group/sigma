import numpy as np
import pandas as pd
import pytest

from ml.features import build_features


def _make_ohlcv(n: int = 60) -> pd.DataFrame:
    np.random.seed(42)
    close = 150 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    volume = np.random.randint(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"close": close, "high": high, "low": low, "open": close, "volume": volume})


def test_build_features_columns():
    df = _make_ohlcv()
    features = build_features(df)
    # Core schema (raw ema_20/ema_50 levels are intentionally not emitted —
    # not cross-symbol portable) plus the Phase E additions.
    expected_cols = {"rsi_14", "roc_10", "ema_ratio", "bb_width", "atr_14", "volume_ratio",
                     "ret_1d", "ret_5d", "zscore_20", "vol_regime", "rsi_7", "hl_range", "up_frac_10"}
    assert expected_cols.issubset(set(features.columns))


def test_build_features_no_nan():
    df = _make_ohlcv(80)
    features = build_features(df)
    assert not features.isnull().any().any()


def test_build_features_rsi_range():
    df = _make_ohlcv(80)
    features = build_features(df)
    assert features["rsi_14"].between(0, 100).all()
