"""Risk management, sizing, exits, and portfolio management.

Bodies ported from razorBill (`risk_manager.py` → `manager.py`,
`portfolio_manager.py` → `portfolio.py`, plus `sizing.py` and `exits.py`
unchanged in name). The pure logic functions are unchanged from razorBill;
persistence is delegated to the worker tick which uses sigma's ORM."""

from __future__ import annotations

from .exits import compute_exit_orders, compute_exit_orders_advanced  # noqa: F401
from .manager import RiskManager, RiskMetrics  # noqa: F401
from .portfolio import PortfolioManager  # noqa: F401
from .sizing import PositionSizer, Sizing, SizingMethod  # noqa: F401

__all__ = [
    "compute_exit_orders",
    "compute_exit_orders_advanced",
    "RiskManager",
    "RiskMetrics",
    "PortfolioManager",
    "PositionSizer",
    "Sizing",
    "SizingMethod",
]
