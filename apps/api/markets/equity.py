from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from .base import MarketAdapter
from .equity_data import fetch_equity_ohlcv

_NY = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)


class EquityAdapter(MarketAdapter):
    asset_class = "equity"

    def fetch_ohlcv(self, symbol: str, timeframe: str = "daily") -> pd.DataFrame:
        """Reliable multi-source OHLCV (Tiingo → Alpaca → yfinance).

        Source order and credentials come from settings.equity_data_providers;
        see markets/equity_data.py. Raises ValueError if every provider fails."""
        return fetch_equity_ohlcv(symbol, timeframe)

    def is_market_open(self, ts: datetime | None = None) -> bool:
        ts = ts or self._now()
        local = ts.astimezone(_NY)
        if local.weekday() >= 5:
            return False
        return _OPEN <= local.time() < _CLOSE
