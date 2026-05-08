from __future__ import annotations

import os

from .base import UniverseSelector


class DynamicCryptoUniverse(UniverseSelector):
    """Volatility × liquidity ranked Coinbase universe.

    Skeleton — full ranking logic is ported from razorBill's
    `_select_dynamic_universe()` (uses Coinbase /products + recent candles).
    For now returns a small static fallback so the worker is runnable end-to-
    end before the port lands."""

    asset_class = "crypto"

    def __init__(self) -> None:
        self._fallback = os.getenv(
            "CRYPTO_UNIVERSE", "BTC-USD,ETH-USD,SOL-USD,LINK-USD,AVAX-USD"
        )

    def select(self) -> list[str]:
        return [s.strip().upper() for s in self._fallback.split(",") if s.strip()]
