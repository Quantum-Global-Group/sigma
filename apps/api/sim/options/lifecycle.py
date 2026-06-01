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

    action == "mark"  → still open; `unrealized_pnl` + `current_px` updated.
    action == "close" → position closes; `realized_pnl` booked. `outcome` says why
                        (exercised/assigned/expired_worthless/time_stop/stop_loss/
                        take_profit/trailing_stop).
    """
    action: str                      # mark | close
    current_px: float                # per-share theoretical (or intrinsic) value
    unrealized_pnl: float            # populated for "mark"; 0 once closing
    realized_pnl: float              # populated for "close"
    outcome: str
    commission: float = 0.0
    high_water_value: float = 0.0    # running max option value (for trailing); persist on "mark"

    @property
    def closes(self) -> bool:
        return self.action == "close"


def _close_at_value(value, entry_price, qty, multiplier, side, commission_per_contract,
                    outcome, high_water) -> "OptionAction":
    """Book realized P&L closing a leg at `value` (theoretical mark)."""
    commission = commission_per_contract * qty
    sign = 1.0 if side == "long" else -1.0
    realized = sign * (value - entry_price) * multiplier * qty - commission
    return OptionAction("close", current_px=value, unrealized_pnl=0.0,
                        realized_pnl=realized, outcome=outcome, commission=commission,
                        high_water_value=high_water)


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
    high_water_value: float | None = None,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
    trailing_pct: float = 0.0,
    trailing_activate_pct: float = 0.0,
    external_exit: str | None = None,
) -> OptionAction:
    """Decide settle / stop / take-profit / trailing / external / time-stop / mark for
    one held option leg. Pure. Price-based exits act on the option's *premium* vs entry;
    `external_exit` is an underlying-derived reason (ATR/vol/trend) the caller computes.

    Priority: expiry settlement (T<=0) → stop-loss → take-profit → trailing-stop →
    external → time-stop (hold_days>=max) → mark. Each price exit is disabled when its
    pct is 0; external_exit is honored only when no premium exit already fired."""
    if T <= 0:
        s = settle_at_expiry(
            right=right, strike=strike, qty=qty, entry_price=entry_price,
            S_expiry=spot, side=side, multiplier=multiplier,
            commission_per_contract=commission_per_contract,
        )
        return OptionAction("close", current_px=s.payoff, unrealized_pnl=0.0,
                            realized_pnl=s.realized_pnl, outcome=s.outcome, commission=s.commission)

    value = option_value(right, spot, strike, T, r, sigma, american=True)
    hw = max(high_water_value if high_water_value is not None else entry_price, value)

    def close(outcome: str) -> OptionAction:
        return _close_at_value(value, entry_price, qty, multiplier, side,
                               commission_per_contract, outcome, hw)

    # Price-based exits (long-option premium convention).
    if stop_loss_pct > 0 and value <= entry_price * (1.0 - stop_loss_pct):
        return close("stop_loss")
    if take_profit_pct > 0 and value >= entry_price * (1.0 + take_profit_pct):
        return close("take_profit")
    if (
        trailing_pct > 0
        and hw >= entry_price * (1.0 + trailing_activate_pct)   # only after it ran up
        and value <= hw * (1.0 - trailing_pct)                  # ...then pulled back
    ):
        return close("trailing_stop")

    # Underlying-derived exit (ATR-trailing / vol-regime / trend-reversal), computed by
    # the worker from the underlying bars so this stays pure + df-free.
    if external_exit:
        return close(external_exit)

    if hold_days >= max_hold_days:
        return close("time_stop")

    sign = 1.0 if side == "long" else -1.0
    unreal = sign * (value - entry_price) * multiplier * qty
    return OptionAction("mark", current_px=value, unrealized_pnl=unreal,
                        realized_pnl=0.0, outcome="held", high_water_value=hw)
