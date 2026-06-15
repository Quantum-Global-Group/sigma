"""Options income — harvest the volatility risk premium with DEFINED risk.

The research (`scripts/vol_premium_experiment.py`) found the vol risk premium is
real and large but **uninvestable naked** (short vol drew down −92%, lost −69% in
both 2018 and 2020). The honest way to collect it is a *defined-risk* structure
where the maximum loss is capped per trade — a **put credit spread**: sell a put
below the market and buy a further-out put that caps the downside. You collect a
small premium most months; a crash costs you the (bounded) spread width, never
more.

This module is the **brain**: given the underlying price and a risk budget, it
picks the strikes and sizes the contracts so the worst case can't exceed the
budget. It does NOT place orders — live execution needs an Alpaca options path
(multi-leg orders + chain quotes), which is the next engineering step. Pure and
unit-tested; the premium actually collected comes from live quotes at fill time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _round_to(x: float, increment: float) -> float:
    return round(x / increment) * increment


@dataclass(frozen=True)
class PutCreditSpread:
    short_strike: float       # sell this put (collect premium)
    long_strike: float        # buy this put (caps the loss)
    width: float              # short - long, in $
    contracts: int            # number of spreads
    max_loss: float           # bounded worst case in $ (before premium offset)

    @property
    def is_tradeable(self) -> bool:
        return self.contracts >= 1 and self.width > 0


def monthly_risk_budget(equity: float, sleeve_frac: float) -> float:
    """Dollars of capped risk to deploy this month — a small sleeve of the book.

    This is the MOST you can lose on the options sleeve if every spread goes
    maximally against you; keep `sleeve_frac` small (≈0.05–0.10)."""
    return max(0.0, float(equity) * float(sleeve_frac))


def select_put_credit_spread(
    spot: float,
    *,
    risk_budget_usd: float,
    otm_pct: float = 0.05,
    width_pct: float = 0.02,
    multiplier: int = 100,
    strike_increment: float = 1.0,
) -> PutCreditSpread:
    """Pick a capped-risk put credit spread ~`otm_pct` below `spot`.

    short strike ≈ spot·(1−otm_pct); long strike one `width_pct`·spot below it
    (≥ one increment). Contracts are sized so contracts·width·multiplier ≤
    risk_budget — the bounded max loss. Returns a non-tradeable spread
    (contracts=0) when the budget can't cover even one."""
    if spot <= 0 or risk_budget_usd <= 0:
        return PutCreditSpread(0.0, 0.0, 0.0, 0, 0.0)

    short_strike = _round_to(spot * (1.0 - otm_pct), strike_increment)
    long_strike = _round_to(short_strike - spot * width_pct, strike_increment)
    if long_strike >= short_strike:                      # ensure a real, ≥1-increment width
        long_strike = short_strike - strike_increment
    width = short_strike - long_strike
    if width <= 0:
        return PutCreditSpread(short_strike, long_strike, 0.0, 0, 0.0)

    per_contract_risk = width * multiplier
    contracts = int(math.floor(risk_budget_usd / per_contract_risk))
    return PutCreditSpread(
        short_strike=short_strike,
        long_strike=long_strike,
        width=width,
        contracts=max(0, contracts),
        max_loss=max(0, contracts) * per_contract_risk,
    )
