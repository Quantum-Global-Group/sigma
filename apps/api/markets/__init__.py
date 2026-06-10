"""Market adapters — one per asset class.

The pipeline calls `get_market_adapter(asset_class).fetch_ohlcv(...)` rather
than reaching into Tiingo/Alpaca/Coinbase directly. New asset classes plug in by
implementing `MarketAdapter` and registering here.
"""

from __future__ import annotations

from .base import MarketAdapter
from .crypto import CoinbaseAdapter
from .equity import EquityAdapter
from .moomoo import MoomooAdapter
from .oanda import OandaAdapter

_REGISTRY: dict[str, MarketAdapter] = {
    "equity": EquityAdapter(),
    "crypto": CoinbaseAdapter(),
    # Underlying OHLCV for the option asset class (option chains live behind
    # markets/options.py::OptionDataProvider, not this OHLCV adapter).
    "option": MoomooAdapter(),
    # Forex (currency pairs) via OANDA v20 REST.
    "forex": OandaAdapter(),
}


def get_market_adapter(asset_class: str) -> MarketAdapter:
    try:
        return _REGISTRY[asset_class]
    except KeyError as exc:
        raise ValueError(f"Unknown asset_class: {asset_class!r}") from exc


__all__ = ["MarketAdapter", "get_market_adapter"]
