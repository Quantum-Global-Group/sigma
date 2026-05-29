"""Options strategy layer — structures (spreads/condors/…) + candidate selection.

Turns an underlying directional view + regime + IV into a concrete option
*structure* with a known risk profile, then ranks candidates by EV/signal/
liquidity/risk. Consumes markets/options.py quotes and options_math.
"""

from __future__ import annotations

from .strategies import (
    StrategyLeg,
    OptionStructure,
    STRATEGY_BUILDERS,
    build_structure,
)
from .selection import Candidate, applicable_strategies, select_candidates

__all__ = [
    "StrategyLeg",
    "OptionStructure",
    "STRATEGY_BUILDERS",
    "build_structure",
    "Candidate",
    "applicable_strategies",
    "select_candidates",
]
