"""
RazorBill - Crypto Trading Bot

A ranking-based crypto trading system using machine learning,
regime detection, and sentiment analysis.
"""

__version__ = "0.1.0"
__author__ = "RazorBill Team"

from .config import settings
from .models import FeatureEngineer, SequenceBuilder, RankingModel
from .strategy import detect_regime, fuse_signal, RiskState, apply_risk, size_position
from .execution import PaperExecutor, get_executor
from .exits import compute_exit_orders
from .reporting import compute_metrics, compute_equity_curve

__all__ = [
    "settings",
    "FeatureEngineer",
    "SequenceBuilder", 
    "RankingModel",
    "detect_regime",
    "fuse_signal",
    "RiskState",
    "apply_risk",
    "size_position",
    "PaperExecutor",
    "get_executor",
    "compute_exit_orders",
    "compute_metrics",
    "compute_equity_curve",
]
