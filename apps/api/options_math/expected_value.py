"""Expected-value engine + liquidity/risk trade filters (Moomoo doc §4.2, §4.4).

The system trades only when EV is positive after costs AND the contract clears
hard liquidity/risk gates. Both are pure functions over already-fetched quote +
Greek data, so selection logic stays testable and broker-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .volatility import spread_pct


@dataclass(frozen=True)
class LiquidityFilters:
    """Hard reject thresholds. None disables an individual gate."""
    max_spread_pct: float = 0.10        # reject if (ask-bid)/mid > 10%
    min_volume: int = 10
    min_open_interest: int = 50
    max_abs_theta_per_day: Optional[float] = None   # vs holding period, set by caller
    delta_range: Optional[tuple[float, float]] = None  # e.g. (0.20, 0.80) by |delta|
    max_iv: Optional[float] = None      # reject extreme IV without edge


@dataclass(frozen=True)
class EVResult:
    ev: float                 # expected $ value per contract-share, net of costs
    ev_per_premium: float     # risk-adjusted: ev / premium
    gross: float
    costs: float
    positive: bool


def expected_value(
    prob_itm: float,
    expected_payoff: float,
    premium: float,
    fees: float = 0.0,
    slippage: float = 0.0,
) -> EVResult:
    """Option EV = P_ITM * E[payoff] - premium - fees - slippage  (doc §4.4).

    `expected_payoff` is the conditional expected payoff given ITM (per share);
    `premium` is the price paid (per share). Costs are absolute per share.
    """
    prob_itm = max(0.0, min(1.0, prob_itm))
    gross = prob_itm * expected_payoff
    costs = premium + fees + slippage
    ev = gross - costs
    ev_per_premium = ev / premium if premium > 0 else 0.0
    return EVResult(ev=ev, ev_per_premium=ev_per_premium, gross=gross, costs=costs, positive=ev > 0)


def passes_filters(
    *,
    bid: float,
    ask: float,
    volume: int,
    open_interest: int,
    delta: float,
    iv: float,
    theta_per_day: Optional[float],
    filters: LiquidityFilters,
) -> tuple[bool, list[str]]:
    """Return (ok, reasons). reasons lists every gate that tripped (for the audit log)."""
    reasons: list[str] = []

    sp = spread_pct(bid, ask)
    if filters.max_spread_pct is not None and sp > filters.max_spread_pct:
        reasons.append(f"spread {sp:.3f} > {filters.max_spread_pct}")
    if filters.min_volume is not None and volume < filters.min_volume:
        reasons.append(f"volume {volume} < {filters.min_volume}")
    if filters.min_open_interest is not None and open_interest < filters.min_open_interest:
        reasons.append(f"open_interest {open_interest} < {filters.min_open_interest}")
    if filters.delta_range is not None:
        lo, hi = filters.delta_range
        if not (lo <= abs(delta) <= hi):
            reasons.append(f"|delta| {abs(delta):.3f} outside [{lo},{hi}]")
    if filters.max_iv is not None and iv > filters.max_iv:
        reasons.append(f"iv {iv:.3f} > {filters.max_iv}")
    if (
        filters.max_abs_theta_per_day is not None
        and theta_per_day is not None
        and abs(theta_per_day) > filters.max_abs_theta_per_day
    ):
        reasons.append(f"|theta/day| {abs(theta_per_day):.4f} > {filters.max_abs_theta_per_day}")

    return (len(reasons) == 0, reasons)
