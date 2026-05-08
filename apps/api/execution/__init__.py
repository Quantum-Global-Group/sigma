"""Order execution adapters.

`get_executor()` returns the executor configured by `settings.executor_mode`
(paper | coinbase). Live ports of razorBill's PaperExecutor and
CoinbaseExecutor are loaded lazily so the API process doesn't pay the import
cost when the worker isn't running."""

from __future__ import annotations

from config import settings

from .base import Executor, Fill, OrderRequest


def get_executor() -> Executor:
    mode = settings.executor_mode
    if mode == "paper":
        from .paper import PaperExecutor
        return PaperExecutor()
    if mode == "coinbase":
        from .coinbase import CoinbaseExecutor
        return CoinbaseExecutor()
    raise ValueError(f"Unknown executor_mode: {mode!r}")


__all__ = ["Executor", "Fill", "OrderRequest", "get_executor"]
