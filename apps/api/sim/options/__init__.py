"""Options simulator — spread-aware fills, expiry/assignment lifecycle, and a
purged walk-forward backtester. Pure + deterministic (seedable) for testing."""

from __future__ import annotations

from .fill_model import OptionFill, simulate_option_fill
from .lifecycle import (
    Settlement,
    intrinsic_value,
    option_value,
    settle_at_expiry,
)
from .backtester import (
    BacktestResult,
    Trade,
    purged_walkforward_splits,
    backtest_single_leg,
)

__all__ = [
    "OptionFill",
    "simulate_option_fill",
    "Settlement",
    "intrinsic_value",
    "option_value",
    "settle_at_expiry",
    "BacktestResult",
    "Trade",
    "purged_walkforward_splits",
    "backtest_single_leg",
]
