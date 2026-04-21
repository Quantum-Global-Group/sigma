import pandas as pd
import yfinance as yf

TIMEFRAME_PERIOD: dict[str, str] = {
    "daily": "6mo",
    "4h": "60d",
    "hourly": "7d",
}

TIMEFRAME_INTERVAL: dict[str, str] = {
    "daily": "1d",
    "4h": "1h",   # yfinance doesn't support 4h natively; use 1h and resample downstream
    "hourly": "1h",
}


def fetch_ohlcv(ticker: str, timeframe: str = "daily") -> pd.DataFrame:
    period = TIMEFRAME_PERIOD.get(timeframe, "6mo")
    interval = TIMEFRAME_INTERVAL.get(timeframe, "1d")

    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data returned for ticker: {ticker}")

    # Flatten multi-index columns yfinance v0.2+ may return
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.lower)
    df.index.name = "date"
    return df
