"""Transaction-cost model — shared by research harnesses and (when wired) serving.

The alpha-research program optimizes *net-of-cost* risk-adjusted return, not raw
accuracy. A signal that is right 60% of the time but pays more in spread/slippage
than it earns is a loser. These helpers turn gross per-trade returns into net
returns and give a single place to define per-asset round-trip cost.

All functions are pure and unit-tested. Costs are expressed in basis points (bps);
1 bp = 0.0001 = 0.01%.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from config import settings

# Fallback defaults if config is unavailable (kept in sync with config.py).
_DEFAULT_BPS = {"equity": 2.0, "forex": 1.0, "crypto": 8.0}


def cost_bps(asset_class: str) -> float:
    """Round-trip transaction cost in basis points for an asset class."""
    table = {
        "equity": getattr(settings, "cost_bps_equity", _DEFAULT_BPS["equity"]),
        "forex": getattr(settings, "cost_bps_forex", _DEFAULT_BPS["forex"]),
        "crypto": getattr(settings, "cost_bps_crypto", _DEFAULT_BPS["crypto"]),
    }
    return float(table.get(asset_class, _DEFAULT_BPS.get(asset_class, 2.0)))


def cost_frac(asset_class: str, round_trips: float = 1.0) -> float:
    """Cost as a return fraction (bps / 1e4), scaled by number of round trips."""
    return round_trips * cost_bps(asset_class) / 1e4


def apply_cost(gross_return: float, asset_class: str, round_trips: float = 1.0) -> float:
    """Net return after subtracting round-trip cost from a single gross return."""
    return float(gross_return) - cost_frac(asset_class, round_trips)


def net_returns(
    gross: Sequence[float],
    asset_class: str,
    traded_mask: Sequence[bool] | None = None,
) -> np.ndarray:
    """Vectorized net returns: subtract round-trip cost on every traded bar.

    `traded_mask` (default: all True) marks bars where a position was opened/closed
    and thus incurs cost; untraded bars keep their gross value (typically 0)."""
    g = np.asarray(gross, dtype=float)
    if traded_mask is None:
        mask = np.ones_like(g, dtype=bool)
    else:
        mask = np.asarray(traded_mask, dtype=bool)
    return g - mask * cost_frac(asset_class)


def passes_net_edge(predicted_return: float, asset_class: str) -> bool:
    """True if the expected edge clears the round-trip cost (skip marginal trades).

    A signal whose |predicted_return| does not exceed transaction cost is a
    guaranteed net loser in expectation, so it should not be traded."""
    return abs(float(predicted_return)) > cost_frac(asset_class)


def max_drawdown(returns: Sequence[float]) -> float:
    """Max peak-to-trough drop of the cumulative (additive) return curve. >= 0."""
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    return float(np.max(peak - eq))


def sharpe(returns: Sequence[float], periods_per_year: int = 252) -> float | None:
    """Annualized Sharpe ratio of a per-bar return series. None if undefined."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return None
    sd = r.std(ddof=1)
    if sd == 0 or not np.isfinite(sd):
        return None
    return float(r.mean() / sd * np.sqrt(periods_per_year))
