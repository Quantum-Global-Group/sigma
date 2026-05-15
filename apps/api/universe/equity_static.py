from __future__ import annotations

import os

from .base import UniverseSelector


class StaticEquityUniverse(UniverseSelector):
    """Comma-separated equity universe from EQUITY_UNIVERSE env var."""

    asset_class = "equity"

    def __init__(self, default: str = "AAPL,MSFT,NVDA,GOOG,AMZN") -> None:
        self._default = default

    def select(self) -> list[str]:
        raw = os.getenv("EQUITY_UNIVERSE", self._default)
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
