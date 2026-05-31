from __future__ import annotations

import os

from .base import UniverseSelector


class StaticForexUniverse(UniverseSelector):
    """Currency pairs to trade, from the FOREX_UNIVERSE env var.

    Defaults to liquid USD-quote majors so paper PnL is exact (PnL for a
    USD-quote pair like EUR_USD is already in USD; USD-base/cross pairs are
    denominated in the quote currency). Pairs use OANDA's underscore format.
    """

    asset_class = "forex"

    def __init__(self, default: str = "EUR_USD,GBP_USD,AUD_USD,USD_JPY,USD_CAD") -> None:
        self._default = default

    def select(self) -> list[str]:
        raw = os.getenv("FOREX_UNIVERSE", self._default)
        out: list[str] = []
        for s in raw.split(","):
            s = s.strip().upper().replace("/", "_").replace("-", "_")
            if not s:
                continue
            if "_" not in s and len(s) == 6:
                s = f"{s[:3]}_{s[3:]}"
            out.append(s)
        return out
