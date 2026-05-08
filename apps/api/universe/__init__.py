"""Universe selection — which symbols the worker trades each cycle.

Equity: static configured list (default).
Crypto: razorBill's volatility×liquidity dynamic universe (port in subtree)."""

from __future__ import annotations

from .base import UniverseSelector
from .equity_static import StaticEquityUniverse

__all__ = ["UniverseSelector", "StaticEquityUniverse", "get_universe_selector"]


def get_universe_selector(asset_class: str) -> UniverseSelector:
    if asset_class == "equity":
        return StaticEquityUniverse()
    if asset_class == "crypto":
        # Lazy import — Coinbase HTTP fetch shouldn't block API boot.
        from .crypto_dynamic import DynamicCryptoUniverse
        return DynamicCryptoUniverse()
    raise ValueError(f"Unknown asset_class: {asset_class!r}")
