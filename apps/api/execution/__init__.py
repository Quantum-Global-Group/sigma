"""Order execution adapters.

`get_executor(asset_class)` returns the executor configured for that asset
class:
  crypto → settings.crypto_executor   (coinbase | paper)
  equity → settings.equity_executor   (alpaca   | paper)
  option → settings.option_executor   (moomoo   | paper)
  forex  → settings.forex_executor    (oanda | mt5 | paper)

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
    if asset_class == "option":
        return (settings.option_executor or "paper").lower()
    if asset_class == "forex":
        return (settings.forex_executor or "paper").lower()
    return "paper"


def resolve_account_mode(account) -> str | None:
    """Executor mode for a TradingAccount row, or None for legacy resolution.

    `broker='house'` (the migration-013 sentinel for the worker's own book) and
    `account=None` both mean "use the per-asset-class env settings" — exactly
    the pre-multi-account behavior. Real accounts map `broker` directly to an
    executor mode. NOTE: per-account credentials are deferred to the vault work
    (Tier 3.3); executors still read the global broker env, so two accounts on
    the same broker share credentials for now — their DB books stay isolated
    via account_id, but broker-side independence is not yet real."""
    if account is None:
        return None
    broker = (getattr(account, "broker", "") or "").lower()
    if broker in ("", "house"):
        return None
    return broker


def get_executor(asset_class: str = "crypto", account=None) -> Executor:
    mode = resolve_account_mode(account) or _resolve_mode(asset_class)
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
    "resolve_account_mode",
]
