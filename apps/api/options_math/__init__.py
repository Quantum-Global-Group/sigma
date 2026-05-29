"""Options math — pure pricing, Greeks, volatility analytics, and EV gating.

Dependency-light (numpy + scipy only); no Moomoo/DB/network coupling so every
function is trivially unit-testable. Conventions:
  - rates/vols are annualized decimals (r=0.05, sigma=0.20)
  - time to expiry T is in years
  - "right" is "call" | "put"
  - prices are per-share (multiply by 100 for a standard US equity contract)
"""

from __future__ import annotations

from .black_scholes import bs_price, bs_greeks, implied_vol
from .binomial_tree import binomial_price, binomial_greeks
from .monte_carlo import mc_price
from .greeks import Greeks, greeks as compute_greeks
from .volatility import (
    realized_vol,
    iv_rank,
    iv_percentile,
    vol_skew,
    spread_pct,
)
from .expected_value import (
    LiquidityFilters,
    EVResult,
    expected_value,
    passes_filters,
)

__all__ = [
    "bs_price",
    "bs_greeks",
    "implied_vol",
    "binomial_price",
    "binomial_greeks",
    "mc_price",
    "Greeks",
    "compute_greeks",
    "realized_vol",
    "iv_rank",
    "iv_percentile",
    "vol_skew",
    "spread_pct",
    "LiquidityFilters",
    "EVResult",
    "expected_value",
    "passes_filters",
]
