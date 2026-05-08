from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from .base import MarketAdapter

_TIMEFRAME_PERIOD: dict[str, str] = {
    "daily": "6mo",
    "4h": "60d",
    "hourly": "7d",
}
_TIMEFRAME_INTERVAL: dict[str, str] = {
    "daily": "1d",
    "4h": "1h",
    "hourly": "1h",
}

_NY = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)


class EquityAdapter(MarketAdapter):
    asset_class = "equity"

    def fetch_ohlcv(self, symbol: str, timeframe: str = "daily") -> pd.DataFrame:
        period = _TIMEFRAME_PERIOD.get(timeframe, "6mo")
        interval = _TIMEFRAME_INTERVAL.get(timeframe, "1d")

        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No data returned for ticker: {symbol}")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)
        df.index.name = "date"
        return df

    def is_market_open(self, ts: datetime | None = None) -> bool:
        ts = ts or self._now()
        local = ts.astimezone(_NY)
        if local.weekday() >= 5:
            return False
        return _OPEN <= local.time() < _CLOSE
