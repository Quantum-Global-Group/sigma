from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from .base import MarketAdapter

logger = logging.getLogger(__name__)

# Coinbase Advanced Trade granularities (seconds → name).
_TIMEFRAME_GRANULARITY: dict[str, str] = {
    "1m":    "ONE_MINUTE",
    "5m":    "FIVE_MINUTE",
    "hourly": "ONE_HOUR",
    "4h":    "ONE_HOUR",   # request hourly and resample if needed
    "daily":  "ONE_DAY",
}

_TIMEFRAME_LOOKBACK: dict[str, timedelta] = {
    "1m":     timedelta(hours=4),
    "5m":     timedelta(days=1),
    "hourly": timedelta(days=14),
    "4h":     timedelta(days=60),
    "daily":  timedelta(days=180),
}


class CoinbaseAdapter(MarketAdapter):
    """Crypto adapter backed by Coinbase Advanced Trade public candles.

    Uses the Coinbase SDK if available (`coinbase-advanced-py`); otherwise
    falls back to the public REST endpoint via httpx. The fallback path keeps
    local dev working without configuring API credentials, since public market
    data does not require auth."""

    asset_class = "crypto"

    def __init__(self, client: Optional[object] = None):
        self._client = client

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("/", "-")
        if "-" not in s:
            # default quote currency
            s = f"{s}-USD"
        return s

    def fetch_ohlcv(self, symbol: str, timeframe: str = "5m") -> pd.DataFrame:
        product_id = self.normalize_symbol(symbol)
        granularity = _TIMEFRAME_GRANULARITY.get(timeframe, "FIVE_MINUTE")
        lookback = _TIMEFRAME_LOOKBACK.get(timeframe, timedelta(days=1))

        end = self._now()
        start = end - lookback

        candles = self._fetch_candles(product_id, start, end, granularity)
        if not candles:
            raise ValueError(f"No candles returned for {product_id}")

        df = pd.DataFrame(candles, columns=["start", "low", "high", "open", "close", "volume"])
        df["ts"] = pd.to_datetime(df["start"].astype(int), unit="s", utc=True)
        df = df.drop(columns=["start"]).set_index("ts").sort_index()
        df = df.astype(float)
        df.index.name = "date"
        # Reorder for consistency with yfinance shape
        return df[["open", "high", "low", "close", "volume"]]

    def is_market_open(self, ts: datetime | None = None) -> bool:
        return True

    # ---- internal -------------------------------------------------------

    def _fetch_candles(self, product_id: str, start: datetime, end: datetime, granularity: str):
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for the Coinbase adapter") from exc

        url = f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles"
        params = {
            "start": str(int(start.timestamp())),
            "end": str(int(end.timestamp())),
            "granularity": granularity,
        }
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        return data.get("candles", [])
