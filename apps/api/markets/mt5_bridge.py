"""MT5 bridge market-data adapter.

The MetaTrader5 Python package must run beside a logged-in Windows terminal, so
SIGMA talks to a small HTTP bridge instead of importing MetaTrader5 on the DGX.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx
import pandas as pd

from config import settings

from .base import MarketAdapter
from .oanda import OandaAdapter

logger = logging.getLogger(__name__)


class Mt5BridgeAdapter(MarketAdapter):
    asset_class = "forex"
    name = "mt5_bridge"

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        secret: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = (base_url or settings.mt5_bridge_url).rstrip("/")
        self.secret = secret if secret is not None else settings.mt5_bridge_secret
        self._client = client

    @staticmethod
    def mt5_symbol(symbol: str) -> str:
        return symbol.upper().replace("/", "").replace("-", "").replace("_", "")

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("/", "_").replace("-", "_")
        if "_" not in s and len(s) == 6:
            s = f"{s[:3]}_{s[3:]}"
        return s

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=settings.mt5_bridge_timeout_seconds)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {"X-MT5-Bridge-Secret": self.secret} if self.secret else {}

    def fetch_ohlcv(self, symbol: str, timeframe: str = "4h") -> pd.DataFrame:
        if not self.base_url:
            raise ValueError("MT5 bridge URL missing — set MT5_BRIDGE_URL.")
        resp = self.client.get(
            f"{self.base_url}/candles",
            params={
                "symbol": self.mt5_symbol(symbol),
                "timeframe": timeframe,
                "count": settings.mt5_bridge_candle_count,
            },
            headers=self._headers(),
        )
        resp.raise_for_status()
        candles = resp.json().get("candles", [])
        rows = []
        for c in candles:
            try:
                rows.append({
                    "date": pd.to_datetime(c.get("date") or c.get("time")),
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c.get("volume", 0) or 0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        if not rows:
            raise ValueError(f"No MT5 bridge candles for {symbol!r} ({timeframe})")
        df = pd.DataFrame(rows).set_index("date")
        df.index.name = "date"
        return df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()

    def is_market_open(self, ts: datetime | None = None) -> bool:
        return OandaAdapter(api=object()).is_market_open(ts)
