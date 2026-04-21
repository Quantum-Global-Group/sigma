from __future__ import annotations

from ml.data import fetch_ohlcv
from ml.features import build_features
from ml.inference import SignalResult, predict


def run_signal_pipeline(ticker: str, timeframe: str = "daily") -> SignalResult:
    """Fetch market data, build features, run inference. Returns a SignalResult."""
    df = fetch_ohlcv(ticker, timeframe)
    features = build_features(df)
    return predict(features)
