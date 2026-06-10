"""Order execution adapters.

`get_executor(asset_class)` returns the executor configured for that asset
class:
  crypto → settings.crypto_executor   (coinbase | paper)
  equity → settings.equity_executor   (alpaca   | paper)
  option → settings.option_executor   (moomoo   | paper)
  forex  → settings.forex_executor    (oanda | mt5 | paper)

The legacy global `settings.executor_mode` (pre-dating per-asset settings,
when crypto was the only live venue) still works as a **crypto-only** fallback:
if set to something other than "paper" it overrides `crypto_executor`. It never
affects equity/option/forex — a global override that routed every asset class
to one venue (e.g. equities to Coinbase) was a misconfiguration hazard. Live
ports of each executor are imported lazily so the api process doesn't pay
their import cost unless the worker actually trades."""

from __future__ import annotations

from config import settings

from .base import (
    ExecutionReport,
    Executor,
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
)


def _resolve_mode(asset_class: str) -> str:
    if asset_class == "crypto":
        # Legacy override, crypto-only: executor_mode predates the per-asset
        # settings and historically meant "the crypto venue". It must never
        # leak into other asset classes (EXECUTOR_MODE=coinbase would have
        # routed equity orders to the Coinbase executor).
        legacy = (settings.executor_mode or "paper").lower()
        if legacy not in ("paper", ""):
            return legacy
        return (settings.crypto_executor or "paper").lower()
    if asset_class == "equity":
        return (settings.equity_executor or "paper").lower()
    if asset_class == "option":
        return (settings.option_executor or "paper").lower()
    if asset_class == "forex":
        return (settings.forex_executor or "paper").lower()
    return "paper"


def get_executor(asset_class: str = "crypto") -> Executor:
    mode = _resolve_mode(asset_class)
    if mode == "paper":
        from .paper import PaperExecutor
        return PaperExecutor()
    if mode == "coinbase":
        from .coinbase import CoinbaseExecutor
        return CoinbaseExecutor()
    if mode == "alpaca":
        from .alpaca import AlpacaExecutor
        return AlpacaExecutor()
    if mode == "moomoo":
        from .moomoo import MoomooExecutor
        return MoomooExecutor()
    if mode == "oanda":
        from .oanda import OandaExecutor
        return OandaExecutor()
    if mode in ("mt5", "mt5_bridge"):
        from .mt5_bridge import Mt5BridgeExecutor
        return Mt5BridgeExecutor()
    raise ValueError(f"Unknown executor mode {mode!r} for asset_class {asset_class!r}")


__all__ = [
    "Executor",
    "ExecutionReport",
    "OrderIntent",
    "Order",
    "Fill",
    "OrderStatus",
    "OrderType",
    "Side",
    "TimeInForce",
    "get_executor",
]
