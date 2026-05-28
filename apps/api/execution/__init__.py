"""Order execution adapters.

`get_executor(asset_class)` returns the executor configured for that asset
class:
  crypto → settings.crypto_executor   (coinbase | paper)
  equity → settings.equity_executor   (alpaca   | paper)

The legacy global `settings.executor_mode` still works as a fallback for
older deploys: if it's set to something other than "paper" it overrides the
per-asset default. Live ports of each executor are imported lazily so the api
process doesn't pay their import cost unless the worker actually trades."""

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
    # Legacy override: executor_mode wins if explicitly non-paper.
    legacy = (settings.executor_mode or "paper").lower()
    if legacy not in ("paper", ""):
        return legacy
    if asset_class == "crypto":
        return (settings.crypto_executor or "paper").lower()
    if asset_class == "equity":
        return (settings.equity_executor or "paper").lower()
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
