"""Option fill model — spread-aware, since option spreads are wide.

Unlike the equity/crypto paper model (a bps slippage off a reference price),
option fills are modeled off the bid/ask: a buy pays from mid toward the ask,
a sell receives from mid toward the bid, scaled by `aggression`. Per-contract
commission and a partial-fill fraction round it out. Pure + seedable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OptionFill:
    filled: bool
    price: float            # per-share fill price
    qty: float              # contracts filled
    commission: float       # total $ commission
    slippage_bps: float     # |fill - mid| / mid * 1e4
    reason: str = ""        # populated when not filled


def simulate_option_fill(
    *,
    bid: float,
    ask: float,
    last: float,
    side: str,                       # "buy" | "sell"
    qty: float,
    aggression: float = 0.5,         # 0=mid, 1=full cross to bid/ask
    commission_per_contract: float = 0.65,
    multiplier: int = 100,           # noqa: ARG001 (kept for signature symmetry / future notional use)
    max_spread_pct: Optional[float] = None,
    partial_fill_pct: float = 1.0,
    seed: Optional[int] = None,
) -> OptionFill:
    """Simulate a marketable option fill. `bid`/`ask` are the NBBO; `last` is a
    fallback mid when the book is one-sided. Returns an unfilled result (reason
    set) when there's no usable price or the spread is too wide."""
    if qty <= 0:
        return OptionFill(False, 0.0, 0.0, 0.0, 0.0, "qty <= 0")

    has_book = bid > 0 and ask > 0 and ask >= bid
    mid = (bid + ask) / 2.0 if has_book else last
    if mid <= 0:
        return OptionFill(False, 0.0, 0.0, 0.0, 0.0, "no usable price")

    if max_spread_pct is not None and has_book:
        spread_pct = (ask - bid) / mid
        if spread_pct > max_spread_pct:
            return OptionFill(False, 0.0, 0.0, 0.0, 0.0, f"spread {spread_pct:.3f} > {max_spread_pct}")

    half = (ask - bid) / 2.0 if has_book else 0.0
    a = min(1.0, max(0.0, aggression))
    if side == "buy":
        price = mid + a * half
    elif side == "sell":
        price = mid - a * half
    else:
        return OptionFill(False, 0.0, 0.0, 0.0, 0.0, f"bad side {side!r}")
    price = max(0.0, round(price, 4))

    fill_pct = partial_fill_pct
    if 0 < fill_pct < 1.0:
        rng = random.Random(seed)
        fill_pct = rng.uniform(fill_pct, 1.0)
    filled_qty = qty * fill_pct

    commission = commission_per_contract * filled_qty
    slippage_bps = abs(price - mid) / mid * 10_000.0 if mid > 0 else 0.0
    return OptionFill(
        filled=filled_qty > 0,
        price=price,
        qty=filled_qty,
        commission=commission,
        slippage_bps=round(slippage_bps, 4),
    )
