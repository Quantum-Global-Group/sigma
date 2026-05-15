"""Crypto market adapter — Coinbase Exchange public candles.

Uses Coinbase's public Exchange API (`api.exchange.coinbase.com`) which
razorBill's `data_fetcher.py` proved out: no auth required for public
market data, simple `[ts, low, high, open, close, volume]` response,
pagination by 300-candle windows.

(The Advanced Trade endpoint exists too — `/api/v3/brokerage/...` — but
the Exchange endpoint is simpler and battle-tested in razorBill.)"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from .base import MarketAdapter

logger = logging.getLogger(__name__)

# Coinbase Exchange granularity (seconds). Advanced Trade uses string names;
# the public Exchange API uses integer seconds.
_TIMEFRAME_GRANULARITY: dict[str, int] = {
    "1m":     60,
    "5m":     300,
    "hourly": 3600,
    "1h":     3600,
    "4h":     3600,    # request hourly and let downstream resample if needed
    "daily":  86_400,
    "1d":     86_400,
}

_TIMEFRAME_LOOKBACK: dict[str, timedelta] = {
    "1m":     timedelta(hours=4),
    "5m":     timedelta(days=1),
    "hourly": timedelta(days=14),
    "1h":     timedelta(days=14),
    "4h":     timedelta(days=60),
    "daily":  timedelta(days=180),
    "1d":     timedelta(days=180),
}

_BASE_URL = "https://api.exchange.coinbase.com"
_MAX_CANDLES_PER_REQUEST = 300


class CoinbaseAdapter(MarketAdapter):
    """Crypto adapter backed by Coinbase Exchange public candles."""

    asset_class = "crypto"

    def __init__(self, client: Optional[object] = None):
        self._client = client

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("/", "-")
        if "-" not in s:
            s = f"{s}-USD"
        return s

    def fetch_ohlcv(self, symbol: str, timeframe: str = "5m") -> pd.DataFrame:
        product_id = self.normalize_symbol(symbol)
        granularity = _TIMEFRAME_GRANULARITY.get(timeframe, 300)
        lookback = _TIMEFRAME_LOOKBACK.get(timeframe, timedelta(days=1))

        end = self._now()
        start = end - lookback

        rows = self._fetch_paginated(product_id, start, end, granularity)
        if not rows:
            raise ValueError(f"No candles returned for {product_id}")

        # Coinbase Exchange order: [ts, low, high, open, close, volume]
        df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
        df = df.drop_duplicates(subset="ts").sort_values("ts").set_index("ts")
        df = df.astype(float)
        df.index.name = "date"
        return df[["open", "high", "low", "close", "volume"]]

    def is_market_open(self, ts: datetime | None = None) -> bool:
        return True

    # ---- internal -------------------------------------------------------

    def _fetch_paginated(
        self,
        product_id: str,
        start: datetime,
        end: datetime,
        granularity: int,
    ) -> list[list]:
        """Walk forward in 300-candle windows and concatenate.

        Mirrors razorBill data_fetcher.fetch_candles but synchronous so the
        existing pipeline (sync) can call it without an event loop hop."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for CoinbaseAdapter") from exc

        url = f"{_BASE_URL}/products/{product_id}/candles"
        max_window = timedelta(seconds=_MAX_CANDLES_PER_REQUEST * granularity)

        rows: list[list] = []
        cursor = start
        with httpx.Client(timeout=10.0, headers={"User-Agent": "sigma/1.0"}) as client:
            while cursor < end:
                batch_end = min(cursor + max_window, end)
                params = {
                    "start": int(cursor.timestamp()),
                    "end": int(batch_end.timestamp()),
                    "granularity": granularity,
                }
                try:
                    r = client.get(url, params=params)
                    r.raise_for_status()
                    batch = r.json()
                except httpx.HTTPError:
                    logger.exception("Coinbase fetch failed for %s", product_id)
                    break
                if isinstance(batch, list):
                    rows.extend(batch)
                cursor = batch_end
                # Light rate-limit cushion (Coinbase allows ~10 req/s public)
                time.sleep(0.1)
        return rows
