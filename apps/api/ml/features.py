import numpy as np
import pandas as pd

from config import settings


def build_features(df: pd.DataFrame, headlines: list[str] | None = None) -> pd.DataFrame:
    """Compute technical indicator features from OHLCV data.

    All features are price-normalized so the model generalises across
    symbols with different absolute price levels. Works on any timeframe.

    If `headlines` is provided and HUGGINGFACE_TOKEN is set, a `sentiment_score`
    feature is appended (constant across all rows for this snapshot).
    """
    out = pd.DataFrame(index=df.index)

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    ema_20 = close.ewm(span=20).mean()
    ema_50 = close.ewm(span=50).mean()
    rolling_std = close.rolling(20).std()
    rolling_mean = close.rolling(20).mean()

    # Momentum
    out["rsi_14"] = _rsi(close, 14)
    out["roc_10"] = close.pct_change(10)

    # Trend — normalized; raw EMA levels omitted (not cross-symbol portable)
    out["ema_ratio"] = ema_20 / ema_50                 # >1 = uptrend, <1 = downtrend
    out["ema_trend"]  = (ema_20 > ema_50).astype(float) # binary crossover signal
    out["price_vs_ema20"] = (close - ema_20) / ema_20  # normalized distance from EMA

    # Volatility
    out["bb_width"] = (rolling_std * 2) / rolling_mean
    out["bb_pct"]   = (close - (rolling_mean - rolling_std * 2)) / (rolling_std * 4 + 1e-10)
    # ATR as a fraction of price — the raw dollar ATR was the last price-level
    # feature left (a $200 stock's ATR dwarfs a $60 stock's), letting trees
    # split on price level as a ticker-identity proxy. Renamed so any artifact
    # trained on the old column fails loudly (KeyError → graceful no-model
    # fallback) instead of predicting on silently shifted inputs.
    out["atr_pct"]  = _atr(high, low, close, 14) / (close + 1e-10)

    # MACD histogram (normalized by price level for cross-symbol portability)
    macd_fast = close.ewm(span=12).mean()
    macd_slow = close.ewm(span=26).mean()
    macd_line = macd_fast - macd_slow
    macd_signal = macd_line.ewm(span=9).mean()
    out["macd_hist"] = (macd_line - macd_signal) / (close + 1e-10)

    # Volume
    out["volume_ratio"] = volume / (volume.rolling(20).mean() + 1e-10)

    # Returns at multiple horizons
    out["ret_1d"]  = close.pct_change(1)
    out["ret_3d"]  = close.pct_change(3)
    out["ret_5d"]  = close.pct_change(5)
    out["ret_10d"] = close.pct_change(10)

    # --- Added (Phase E): stronger, price-normalized predictive features ---
    # Mean-reversion: z-score of price vs its 20-bar mean
    out["zscore_20"] = (close - rolling_mean) / (rolling_std + 1e-10)
    # Volatility regime: short vs long realized vol (>1 = vol expanding)
    rets = close.pct_change()
    out["vol_regime"] = rets.rolling(10).std() / (rets.rolling(30).std() + 1e-10)
    # Faster RSI for shorter-horizon momentum
    out["rsi_7"] = _rsi(close, 7)
    # Intrabar range relative to price (range-based volatility)
    out["hl_range"] = (high - low) / (close + 1e-10)
    # Trend persistence: fraction of up-bars over the last 10
    out["up_frac_10"] = (close.diff() > 0).rolling(10).mean()

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
