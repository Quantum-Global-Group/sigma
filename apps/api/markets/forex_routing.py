"""Per-symbol forex routing between OANDA and the MT5 bridge."""

from __future__ import annotations

from functools import lru_cache

from config import settings

from .base import MarketAdapter
from .mt5_bridge import Mt5BridgeAdapter
from .oanda import OandaAdapter


def normalize_forex_symbol(symbol: str) -> str:
    s = symbol.upper().replace("/", "_").replace("-", "_")
    if "_" not in s and len(s) == 6:
        s = f"{s[:3]}_{s[3:]}"
    return s


def compact_forex_symbol(symbol: str) -> str:
    return normalize_forex_symbol(symbol).replace("_", "")


def _configured_mt5_symbols() -> set[str]:
    raw = settings.forex_mt5_symbols or ""
    return {compact_forex_symbol(s.strip()) for s in raw.split(",") if s.strip()}


def is_mt5_symbol(symbol: str) -> bool:
    return compact_forex_symbol(symbol) in _configured_mt5_symbols()


@lru_cache(maxsize=1)
def _oanda_adapter() -> OandaAdapter:
    return OandaAdapter()


@lru_cache(maxsize=1)
def _mt5_adapter() -> Mt5BridgeAdapter:
    return Mt5BridgeAdapter()


def get_forex_adapter(symbol: str) -> MarketAdapter:
    return _mt5_adapter() if is_mt5_symbol(symbol) else _oanda_adapter()


def get_forex_executor(symbol: str):
    if is_mt5_symbol(symbol):
        from execution.mt5_bridge import Mt5BridgeExecutor
        return Mt5BridgeExecutor()
    from execution import get_executor
    return get_executor("forex")
