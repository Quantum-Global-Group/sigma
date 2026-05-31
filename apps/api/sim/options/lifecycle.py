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


@dataclass(frozen=True)
class OptionAction:
    """What to do with a held option leg this cycle.

    action == "mark"      → still open; `unrealized_pnl` + `current_px` updated.
    action == "settle"    → expired; `realized_pnl` booked, position closes.
    action == "time_stop" → max hold reached; closed at theoretical value.
    """
    action: str                      # mark | settle | time_stop
    current_px: float                # per-share theoretical (or intrinsic) value
    unrealized_pnl: float            # populated for "mark"; 0 once closing
    realized_pnl: float              # populated for "settle" / "time_stop"
    outcome: str                     # held | exercised | assigned | expired_worthless | time_stop
    commission: float = 0.0

    @property
    def closes(self) -> bool:
        return self.action in ("settle", "time_stop")


def manage_position(
    *,
    entry_price: float,
    qty: float,
    right: Right,
    strike: float,
    spot: float,
    T: float,
    sigma: float,
    hold_days: int,
    max_hold_days: int,
    side: Side = "long",
    r: float = 0.05,
    multiplier: int = 100,
    commission_per_contract: float = 0.65,
) -> OptionAction:
    """Decide settle / time-stop / mark for one held option leg. Pure.

    Priority: expiry settlement (T<=0) → time stop (hold_days>=max) → mark."""
    if T <= 0:
        s = settle_at_expiry(
            right=right, strike=strike, qty=qty, entry_price=entry_price,
            S_expiry=spot, side=side, multiplier=multiplier,
            commission_per_contract=commission_per_contract,
        )
        return OptionAction("settle", current_px=s.payoff, unrealized_pnl=0.0,
                            realized_pnl=s.realized_pnl, outcome=s.outcome, commission=s.commission)

    value = option_value(right, spot, strike, T, r, sigma, american=True)

    if hold_days >= max_hold_days:
        commission = commission_per_contract * qty
        sign = 1.0 if side == "long" else -1.0
        realized = sign * (value - entry_price) * multiplier * qty - commission
        return OptionAction("time_stop", current_px=value, unrealized_pnl=0.0,
                            realized_pnl=realized, outcome="time_stop", commission=commission)

    sign = 1.0 if side == "long" else -1.0
    unreal = sign * (value - entry_price) * multiplier * qty
    return OptionAction("mark", current_px=value, unrealized_pnl=unreal,
                        realized_pnl=0.0, outcome="held")
