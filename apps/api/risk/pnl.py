"""Mark-to-market helpers — pure P&L math shared by the worker and reporting.

The house book is long-only (BUY entries, SELL exits), so unrealized P&L for an
open position is simply (current - entry) * qty, scaled by the contract
multiplier (1 for equity/crypto/forex, 100 for options). Kept pure so both the
worker tick and any reporting path compute P&L identically.
"""

from __future__ import annotations


def unrealized(entry_px: float, qty: float, current_px: float, multiplier: int = 1) -> float:
    """Unrealized P&L for a long position marked at `current_px`."""
    return (current_px - entry_px) * qty * multiplier


def position_value(qty: float, current_px: float, multiplier: int = 1) -> float:
    """Current market value of a position."""
    return qty * current_px * multiplier
