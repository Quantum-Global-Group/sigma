"""Option lifecycle — intrinsic value, mark-to-market, and expiry settlement.

Covers the events the equity/crypto path never had: cash-settled expiry,
ITM exercise (long) / assignment (short), and mark-to-market for held legs
(theta accrual + unrealized PnL) via the options_math pricers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from options_math import binomial_price, bs_price

Right = Literal["call", "put"]
Side = Literal["long", "short"]


def intrinsic_value(right: Right, S: float, K: float) -> float:
    """Per-share intrinsic value at underlying price S."""
    return max(0.0, (S - K) if right == "call" else (K - S))


def option_value(
    right: Right, S: float, K: float, T: float, r: float, sigma: float,
    american: bool = True,
) -> float:
    """Per-share theoretical value for mark-to-market. American (binomial) for
    US equity options; falls back to intrinsic at/after expiry."""
    if T <= 0:
        return intrinsic_value(right, S, K)
    if american:
        return binomial_price(S, K, T, r, sigma, right, steps=200, american=True)
    return bs_price(S, K, T, r, sigma, right)


@dataclass(frozen=True)
class Settlement:
    realized_pnl: float        # total $ PnL of the closed leg, net of commission
    payoff: float              # per-share intrinsic at expiry
    outcome: str               # exercised | assigned | expired_worthless
    commission: float


def settle_at_expiry(
    *,
    right: Right,
    strike: float,
    qty: float,
    entry_price: float,        # premium per share at entry
    S_expiry: float,
    side: Side = "long",
    multiplier: int = 100,
    commission_per_contract: float = 0.65,
) -> Settlement:
    """Cash-settle a single-leg option at expiry.

    long:  pnl = (intrinsic - entry_premium) * mult * qty - commission
    short: pnl = (entry_premium - intrinsic) * mult * qty - commission
    """
    iv = intrinsic_value(right, S_expiry, strike)
    commission = commission_per_contract * qty
    if side == "long":
        realized = (iv - entry_price) * multiplier * qty - commission
        outcome = "exercised" if iv > 0 else "expired_worthless"
    else:
        realized = (entry_price - iv) * multiplier * qty - commission
        outcome = "assigned" if iv > 0 else "expired_worthless"
    return Settlement(realized_pnl=realized, payoff=iv, outcome=outcome, commission=commission)
