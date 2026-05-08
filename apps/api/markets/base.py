from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

import pandas as pd


class MarketAdapter(ABC):
    """Asset-class-specific market interface.

    Implementations encapsulate the data source (yfinance / Coinbase / ...) and
    the calendar (24/7 vs market hours), so the rest of the pipeline can be
    written once."""

    asset_class: str = ""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Return a DataFrame with lowercase columns: open, high, low, close, volume."""

    @abstractmethod
    def is_market_open(self, ts: datetime | None = None) -> bool:
        """Whether the market is open at `ts` (default: now). Crypto = always."""

    def normalize_symbol(self, symbol: str) -> str:
        """Canonicalize a symbol (e.g. uppercase). Override per asset class."""
        return symbol.upper()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
