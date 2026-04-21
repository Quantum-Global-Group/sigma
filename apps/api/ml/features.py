import numpy as np
import pandas as pd

from config import settings


def build_features(df: pd.DataFrame, headlines: list[str] | None = None) -> pd.DataFrame:
    """Compute technical indicator features from OHLCV data.

    If `headlines` is provided and HUGGINGFACE_TOKEN is set, a `sentiment_score`
    feature is appended (constant across all rows for this snapshot).
    """
    out = pd.DataFrame(index=df.index)

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # Momentum
    out["rsi_14"] = _rsi(close, 14)
    out["roc_10"] = close.pct_change(10)

    # Trend
    out["ema_20"] = close.ewm(span=20).mean()
    out["ema_50"] = close.ewm(span=50).mean()
    out["ema_ratio"] = out["ema_20"] / out["ema_50"]

    # Volatility
    rolling_std = close.rolling(20).std()
    out["bb_width"] = (rolling_std * 2) / close.rolling(20).mean()
    out["atr_14"] = _atr(high, low, close, 14)

    # Volume
    out["volume_ratio"] = volume / volume.rolling(20).mean()

    # Returns
    out["ret_1d"] = close.pct_change(1)
    out["ret_5d"] = close.pct_change(5)

    # Optional sentiment (FinBERT) — added only when token is configured
    if headlines and settings.huggingface_token:
        try:
            from ml.sentiment import score_headlines
            score = score_headlines(headlines)
            out["sentiment_score"] = score
        except Exception:
            pass

    return out.dropna()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()
