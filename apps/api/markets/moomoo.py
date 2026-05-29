"""Moomoo underlying market-data adapter (OpenD `OpenQuoteContext`).

Provides OHLCV for the *underlying* equities behind options, conforming to the
standard `MarketAdapter` contract (lowercase open/high/low/close/volume, `date`
index). Option chains/quotes live in markets/options.py. SDK is lazy-imported;
`quote_ctx` is injectable for tests so CI needs no OpenD gateway.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings

from .base import MarketAdapter

logger = logging.getLogger(__name__)

_NY = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)

# How far back to request per timeframe.
_LOOKBACK = {
    "daily": timedelta(days=180), "1d": timedelta(days=180),
    "hourly": timedelta(days=14), "1h": timedelta(days=14),
    "5m": timedelta(days=5), "1m": timedelta(days=1),
}
_RET_OK = 0  # moomoo.RET_OK


class MoomooAdapter(MarketAdapter):
    asset_class = "option"  # underlying data source for the option asset class

    def __init__(self, quote_ctx: Optional[object] = None) -> None:
        self._ctx = quote_ctx

    @property
    def ctx(self):
        if self._ctx is None:
            from moomoo import OpenQuoteContext  # lazy import
            self._ctx = OpenQuoteContext(host=settings.moomoo_host, port=settings.moomoo_port)
        return self._ctx

    @staticmethod
    def _code(symbol: str) -> str:
        return symbol if "." in symbol else f"US.{symbol}"

    def _ktype(self, timeframe: str):
        from moomoo import KLType
        return {
            "daily": KLType.K_DAY, "1d": KLType.K_DAY,
            "hourly": KLType.K_60M, "1h": KLType.K_60M,
            "5m": KLType.K_5M, "1m": KLType.K_1M,
        }.get(timeframe, KLType.K_DAY)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "daily") -> pd.DataFrame:
        lookback = _LOOKBACK.get(timeframe, timedelta(days=180))
        end = self._now()
        start = end - lookback
        result = self.ctx.request_history_kline(
            code=self._code(symbol),
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            ktype=self._ktype(timeframe),
        )
        # SDK returns (ret, data) or (ret, data, page_key)
        ret, data = result[0], result[1]
        if ret != _RET_OK or data is None or len(data) == 0:
            raise ValueError(f"No Moomoo data for {symbol!r} ({timeframe}): {data}")

        df = pd.DataFrame(data)
        tcol = "time_key" if "time_key" in df.columns else df.columns[0]
        df[tcol] = pd.to_datetime(df[tcol])
        df = df.rename(columns=str.lower).set_index(tcol)
        df.index.name = "date"
        cols = ["open", "high", "low", "close", "volume"]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"Moomoo kline missing columns {missing} for {symbol}")
        return df[cols].astype(float).sort_index()

    def is_market_open(self, ts: datetime | None = None) -> bool:
        ts = ts or self._now()
        local = ts.astimezone(_NY)
        if local.weekday() >= 5:
            return False
        return _OPEN <= local.time() < _CLOSE
