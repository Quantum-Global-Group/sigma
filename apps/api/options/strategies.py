"""Option strategy structures (Moomoo doc §6).

Each builder takes a single-expiry chain of `OptionQuote`s + spot and returns an
`OptionStructure` with concrete legs and an analytic risk profile (max loss/
profit, breakevens, net Greeks). Builders return None when the needed strikes
aren't available in the chain.

Structures: long_call, long_put, call_debit_spread, put_debit_spread,
long_straddle, long_strangle, iron_condor. Net Greeks use quote Greeks when
present, else fall back to Black-Scholes from quote IV.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from markets.options import OptionQuote
from options_math import bs_greeks

Right = str   # "call" | "put"
LegSide = str  # "long" | "short"


@dataclass(frozen=True)
class StrategyLeg:
    quote: OptionQuote
    side: LegSide
    qty: int = 1

    @property
    def signed_qty(self) -> int:
        return self.qty if self.side == "long" else -self.qty


@dataclass(frozen=True)
class OptionStructure:
    name: str
    legs: list[StrategyLeg]
    net_debit: float            # per-share: + = debit paid, - = credit received
    max_loss: float             # $ magnitude of worst case for 1 unit (inf-safe)
    max_profit: float           # $ (may be float('inf'))
    breakevens: list[float]
    net_greeks: dict
    multiplier: int = 100
    metadata: dict = field(default_factory=dict)

    @property
    def is_credit(self) -> bool:
        return self.net_debit < 0


# ---------------------------------------------------------------------------
# chain helpers
# ---------------------------------------------------------------------------

def _by_right(chain: list[OptionQuote], right: Right) -> list[OptionQuote]:
    return [q for q in chain if q.contract.right == right]


def _nearest(chain: list[OptionQuote], right: Right, target_strike: float) -> Optional[OptionQuote]:
    cands = _by_right(chain, right)
    if not cands:
        return None
    return min(cands, key=lambda q: abs(q.contract.strike - target_strike))


def _leg_greeks(q: OptionQuote, spot: float, T: float, r: float) -> dict:
    """Quote Greeks if provided by the broker, else BS from quote IV."""
    if q.delta is not None and q.gamma is not None and q.theta is not None and q.vega is not None:
        return {"delta": q.delta, "gamma": q.gamma, "theta": q.theta, "vega": q.vega, "rho": 0.0}
    sigma = q.implied_vol if q.implied_vol and q.implied_vol > 0 else 0.3
    if sigma > 3:  # broker IV sometimes in percent
        sigma /= 100.0
    return bs_greeks(spot, q.contract.strike, max(T, 1e-6), r, sigma, q.contract.right)


def _net_greeks(legs: list[StrategyLeg], spot: float, T: float, r: float) -> dict:
    out = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    for leg in legs:
        g = _leg_greeks(leg.quote, spot, T, r)
        for k in out:
            out[k] += g.get(k, 0.0) * leg.signed_qty
    return out


def _net_debit(legs: list[StrategyLeg]) -> float:
    return sum(leg.quote.mid * leg.signed_qty for leg in legs)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def _single(chain, spot, T, r, right: Right, name: str) -> Optional[OptionStructure]:
    q = _nearest(chain, right, spot)
    if q is None or q.mid <= 0:
        return None
    legs = [StrategyLeg(q, "long", 1)]
    debit = _net_debit(legs)
    K = q.contract.strike
    be = (K + debit) if right == "call" else (K - debit)
    return OptionStructure(
        name=name, legs=legs, net_debit=debit,
        max_loss=debit * 100, max_profit=float("inf") if right == "call" else (K - debit) * 100,
        breakevens=[round(be, 2)], net_greeks=_net_greeks(legs, spot, T, r),
        metadata={"strike": K},
    )


def long_call(chain, spot, T, r, **kw):
    return _single(chain, spot, T, r, "call", "long_call")


def long_put(chain, spot, T, r, **kw):
    return _single(chain, spot, T, r, "put", "long_put")


def _vertical_debit(chain, spot, T, r, right: Right, width_pct: float, name: str):
    long_q = _nearest(chain, right, spot)
    short_strike = spot * (1 + width_pct) if right == "call" else spot * (1 - width_pct)
    short_q = _nearest(chain, right, short_strike)
    if not long_q or not short_q or long_q.contract.strike == short_q.contract.strike:
        return None
    legs = [StrategyLeg(long_q, "long", 1), StrategyLeg(short_q, "short", 1)]
    debit = _net_debit(legs)
    if debit <= 0:  # not a debit spread as configured
        return None
    width = abs(short_q.contract.strike - long_q.contract.strike)
    max_loss = debit * 100
    max_profit = (width - debit) * 100
    lo = long_q.contract.strike
    be = (lo + debit) if right == "call" else (lo - debit)
    return OptionStructure(
        name=name, legs=legs, net_debit=debit, max_loss=max_loss, max_profit=max_profit,
        breakevens=[round(be, 2)], net_greeks=_net_greeks(legs, spot, T, r),
        metadata={"width": width, "long_strike": lo, "short_strike": short_q.contract.strike},
    )


def call_debit_spread(chain, spot, T, r, width_pct: float = 0.05, **kw):
    return _vertical_debit(chain, spot, T, r, "call", width_pct, "call_debit_spread")


def put_debit_spread(chain, spot, T, r, width_pct: float = 0.05, **kw):
    return _vertical_debit(chain, spot, T, r, "put", width_pct, "put_debit_spread")


def long_straddle(chain, spot, T, r, **kw):
    c = _nearest(chain, "call", spot)
    p = _nearest(chain, "put", spot)
    if not c or not p or c.mid <= 0 or p.mid <= 0:
        return None
    legs = [StrategyLeg(c, "long", 1), StrategyLeg(p, "long", 1)]
    debit = _net_debit(legs)
    K = c.contract.strike
    return OptionStructure(
        name="long_straddle", legs=legs, net_debit=debit, max_loss=debit * 100,
        max_profit=float("inf"), breakevens=[round(K - debit, 2), round(K + debit, 2)],
        net_greeks=_net_greeks(legs, spot, T, r), metadata={"strike": K},
    )


def long_strangle(chain, spot, T, r, width_pct: float = 0.05, **kw):
    c = _nearest(chain, "call", spot * (1 + width_pct))
    p = _nearest(chain, "put", spot * (1 - width_pct))
    if not c or not p or c.mid <= 0 or p.mid <= 0:
        return None
    legs = [StrategyLeg(c, "long", 1), StrategyLeg(p, "long", 1)]
    debit = _net_debit(legs)
    return OptionStructure(
        name="long_strangle", legs=legs, net_debit=debit, max_loss=debit * 100,
        max_profit=float("inf"),
        breakevens=[round(p.contract.strike - debit, 2), round(c.contract.strike + debit, 2)],
        net_greeks=_net_greeks(legs, spot, T, r),
        metadata={"call_strike": c.contract.strike, "put_strike": p.contract.strike},
    )


def iron_condor(chain, spot, T, r, body_pct: float = 0.05, wing_pct: float = 0.10, **kw):
    short_call = _nearest(chain, "call", spot * (1 + body_pct))
    long_call_ = _nearest(chain, "call", spot * (1 + wing_pct))
    short_put = _nearest(chain, "put", spot * (1 - body_pct))
    long_put_ = _nearest(chain, "put", spot * (1 - wing_pct))
    legs_q = [short_call, long_call_, short_put, long_put_]
    if any(q is None or q.mid <= 0 for q in legs_q):
        return None
    legs = [
        StrategyLeg(short_call, "short", 1), StrategyLeg(long_call_, "long", 1),
        StrategyLeg(short_put, "short", 1), StrategyLeg(long_put_, "long", 1),
    ]
    net_debit = _net_debit(legs)          # negative = credit received
    credit = -net_debit
    call_width = abs(long_call_.contract.strike - short_call.contract.strike)
    put_width = abs(short_put.contract.strike - long_put_.contract.strike)
    max_width = max(call_width, put_width)
    max_loss = (max_width - credit) * 100
    max_profit = credit * 100
    return OptionStructure(
        name="iron_condor", legs=legs, net_debit=net_debit, max_loss=max_loss, max_profit=max_profit,
        breakevens=[round(short_put.contract.strike - credit, 2), round(short_call.contract.strike + credit, 2)],
        net_greeks=_net_greeks(legs, spot, T, r),
        metadata={"credit": credit, "call_width": call_width, "put_width": put_width},
    )


STRATEGY_BUILDERS: dict[str, Callable[..., Optional[OptionStructure]]] = {
    "long_call": long_call,
    "long_put": long_put,
    "call_debit_spread": call_debit_spread,
    "put_debit_spread": put_debit_spread,
    "long_straddle": long_straddle,
    "long_strangle": long_strangle,
    "iron_condor": iron_condor,
}


def build_structure(name: str, chain: list[OptionQuote], spot: float, T: float, r: float, **kw):
    builder = STRATEGY_BUILDERS.get(name)
    if builder is None:
        return None
    return builder(chain, spot, T, r, **kw)
