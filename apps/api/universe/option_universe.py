from __future__ import annotations

import os

from .base import UniverseSelector


class OptionUniverse(UniverseSelector):
    """Underlyings to scan for option trades.

    Reads OPTION_UNIVERSE env var (comma-separated tickers). Defaults to a
    small set of liquid names with active options markets. This is deliberately
    narrower than the equity universe — option chains need volume + OI to be
    tradable, so start tight and expand based on live liquidity checks.
    """

    asset_class = "option"

    def __init__(self, default: str = "AAPL,MSFT,NVDA,SPY,QQQ") -> None:
        self._default = default

    def select(self) -> list[str]:
        raw = os.getenv("OPTION_UNIVERSE", self._default)
        return [s.strip().upper() for s in raw.split(",") if s.strip()]
