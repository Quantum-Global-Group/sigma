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
# Options risk layer (P5)
from .greeks import (  # noqa: F401
    GreekExposure,
    GreekLimits,
    HedgeRecommendation,
    aggregate_greeks,
    check_greek_limits,
    delta_hedge,
)
from .kill_switch import HaltThresholds, KillSwitch, evaluate_halt  # noqa: F401
from .audit_log import AuditLog, AuditRecord  # noqa: F401
from .option_sizing import OptionSize, option_position_size  # noqa: F401

__all__ = [
    "compute_exit_orders",
    "compute_exit_orders_advanced",
    "RiskManager",
    "RiskMetrics",
    "PortfolioManager",
    "PositionSizer",
    "Sizing",
    "SizingMethod",
    # options risk layer
    "GreekExposure",
    "GreekLimits",
    "HedgeRecommendation",
    "aggregate_greeks",
    "check_greek_limits",
    "delta_hedge",
    "HaltThresholds",
    "KillSwitch",
    "evaluate_halt",
    "AuditLog",
    "AuditRecord",
    "OptionSize",
    "option_position_size",
]
