"""OANDA forex market-data adapter (v20 REST via oandapyV20).

Provides OHLCV for currency pairs, conforming to the standard `MarketAdapter`
contract (lowercase open/high/low/close/volume, `date` index). OANDA is a cloud
REST broker (practice + live environments) — architecturally like Alpaca, not
Moomoo's local gateway. The SDK is lazy-imported and `api` is injectable for
tests so CI needs no live OANDA account.

Symbols use OANDA's underscore pair format (e.g. `EUR_USD`). Candles are mid
prices; `volume` is OANDA tick volume (fine for technical indicators).
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Optional

import pandas as pd

from config import settings

from .base import MarketAdapter

logger = logging.getLogger(__name__)

# Worker timeframe string → OANDA granularity.
_GRANULARITY = {
    "4h": "H4", "1h": "H1",
    "daily": "D", "1d": "D",
    "15m": "M15", "5m": "M5", "1m": "M1",
}

# How many candles to request per timeframe.
_COUNT = {
    "D": 200, "H4": 360, "H1": 480,
    "M15": 480, "M5": 480, "M1": 500,
}

_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6
_FX_CLOSE = time(21, 0)  # 21:00 UTC


class OandaAdapter(MarketAdapter):
    asset_class = "forex"

    def __init__(self, api: Optional[object] = None) -> None:
        self._api = api

    @property
    def api(self):
        if self._api is None:
            from oandapyV20 import API  # lazy: SDK not on the api boot path
            env = "live" if (settings.oanda_environment or "practice").lower() == "live" else "practice"
            self._api = API(access_token=settings.oanda_api_token, environment=env)
        return self._api

    @staticmethod
    def _instrument(symbol: str) -> str:
        """OANDA pair format: EUR_USD. Accept EUR/USD, EURUSD, eur_usd."""
        s = symbol.upper().replace("/", "_").replace("-", "_")
        if "_" not in s and len(s) == 6:
            s = f"{s[:3]}_{s[3:]}"
        return s

    def normalize_symbol(self, symbol: str) -> str:
        return self._instrument(symbol)

    def _granularity(self, timeframe: str) -> str:
        return _GRANULARITY.get(timeframe, "H4")

    def fetch_ohlcv(self, symbol: str, timeframe: str = "4h") -> pd.DataFrame:
        from oandapyV20.endpoints.instruments import InstrumentsCandles

        gran = self._granularity(timeframe)
        params = {"granularity": gran, "count": _COUNT.get(gran, 360), "price": "M"}
        req = InstrumentsCandles(instrument=self._instrument(symbol), params=params)
        self.api.request(req)
        candles = (req.response or {}).get("candles", [])
        rows = []
        for c in candles:
            if not c.get("complete", False):
                continue  # skip the still-forming current bar
            mid = c.get("mid", {})
            try:
                rows.append({
                    "date": pd.to_datetime(c["time"]),
                    "open": float(mid["o"]),
                    "high": float(mid["h"]),
                    "low": float(mid["l"]),
                    "close": float(mid["c"]),
                    "volume": float(c.get("volume", 0) or 0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        if not rows:
            raise ValueError(f"No OANDA candles for {symbol!r} ({timeframe}/{gran})")

        df = pd.DataFrame(rows).set_index("date")
        df.index.name = "date"
        return df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()

    def is_market_open(self, ts: datetime | None = None) -> bool:
        """Forex is 24/5: open Sun 21:00 UTC → Fri 21:00 UTC; closed weekends."""
        ts = ts or self._now()
        # Ensure UTC for the comparison.
        if ts.tzinfo is not None:
            from datetime import timezone
            ts = ts.astimezone(timezone.utc)
        wd = ts.weekday()
        if wd == _SATURDAY:
            return False
        if wd == _SUNDAY:
            return ts.time() >= _FX_CLOSE          # opens Sunday 21:00 UTC
        if wd == _FRIDAY:
            return ts.time() < _FX_CLOSE           # closes Friday 21:00 UTC
        return True                                 # Mon–Thu always open
