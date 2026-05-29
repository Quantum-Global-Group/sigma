"""Candidate selection — pick + rank option structures for the current view.

Maps the underlying directional signal + regime + IV rank to applicable
strategies (Moomoo doc §6), builds each structure, drops any failing hard
liquidity filters, and ranks the rest by a composite of signal alignment,
liquidity, and risk/reward. Returns ranked `Candidate`s with a rationale dict
for the audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from markets.options import OptionQuote
from ml.regime import Regime
from options_math import LiquidityFilters, passes_filters, spread_pct

from .strategies import OptionStructure, STRATEGY_BUILDERS, build_structure

# tunables (could move to config later)
_STRONG = 0.4          # |signal strength| above which a trend is "strong"
_HIGH_IV = 0.6         # IV rank above which we prefer selling premium
_LOW_IV = 0.3          # IV rank below which long-vol is cheap


@dataclass(frozen=True)
class Candidate:
    strategy: str
    structure: OptionStructure
    score: float
    liquidity: float
    alignment: float
    risk_reward: float
    rationale: dict = field(default_factory=dict)


def applicable_strategies(strength: float, regime: Regime, iv_rank: float) -> list[str]:
    """Ordered candidate strategy names for the view (doc §6)."""
    out: list[str] = []
    bullish = strength >= _STRONG
    bearish = strength <= -_STRONG
    high_iv = iv_rank >= _HIGH_IV
    low_iv = iv_rank <= _LOW_IV

    if bullish:
        # In high IV, prefer the cheaper debit spread over a long single.
        out += ["call_debit_spread", "long_call"] if high_iv else ["long_call", "call_debit_spread"]
    elif bearish:
        out += ["put_debit_spread", "long_put"] if high_iv else ["long_put", "put_debit_spread"]

    # Non-directional / volatility plays.
    if high_iv and regime in (Regime.RANGE, Regime.LOW_VOL):
        out.append("iron_condor")              # sell rich premium into a range
    if low_iv or regime == Regime.HIGH_VOL:
        out += ["long_straddle", "long_strangle"]  # buy cheap vol / expect a move

    # De-dup, preserve order.
    seen, ordered = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


def _liquidity_score(structure: OptionStructure, max_spread: float) -> float:
    spreads = [spread_pct(l.quote.bid, l.quote.ask) for l in structure.legs]
    finite = [s for s in spreads if s != float("inf")]
    if not finite:
        return 0.0
    avg = sum(finite) / len(finite)
    return max(0.0, min(1.0, 1.0 - avg / max_spread))


def _alignment_score(structure: OptionStructure, strength: float) -> float:
    """How well the structure's net delta sign matches the directional view.
    Non-directional structures (|net delta|≈0) score on |strength|-neutrality."""
    net_delta = structure.net_greeks.get("delta", 0.0)
    if abs(net_delta) < 1e-6:
        return 1.0 - abs(strength)         # neutral structure ↔ neutral view
    return max(0.0, (1.0 if (net_delta * strength) > 0 else 0.0)) * min(1.0, abs(strength) + 0.5)


def _risk_reward(structure: OptionStructure) -> float:
    if structure.max_loss <= 0:
        return 5.0
    if structure.max_profit == float("inf"):
        return 3.0                          # capped proxy for unbounded upside
    return min(5.0, structure.max_profit / structure.max_loss)


def _legs_pass_filters(structure: OptionStructure, filters: LiquidityFilters) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for leg in structure.legs:
        q = leg.quote
        ok, rs = passes_filters(
            bid=q.bid, ask=q.ask, volume=q.volume, open_interest=q.open_interest,
            delta=q.delta if q.delta is not None else 0.0,
            iv=q.implied_vol if q.implied_vol is not None else 0.0,
            theta_per_day=q.theta, filters=filters,
        )
        if not ok:
            reasons.extend([f"{q.contract.occ}: {r}" for r in rs])
    return (len(reasons) == 0, reasons)


def select_candidates(
    *,
    chain: list[OptionQuote],
    spot: float,
    strength: float,                 # underlying signal in [-1, 1]
    regime: Regime,
    iv_rank: float,
    T: float,
    r: float = 0.05,
    filters: Optional[LiquidityFilters] = None,
    strategies: Optional[list[str]] = None,
    max_spread: float = 0.25,
    weights: tuple[float, float, float] = (0.5, 0.3, 0.2),  # alignment, liquidity, rr
) -> list[Candidate]:
    """Build + rank candidate structures. Highest score first."""
    filters = filters or LiquidityFilters()
    names = strategies if strategies is not None else applicable_strategies(strength, regime, iv_rank)
    w_align, w_liq, w_rr = weights

    candidates: list[Candidate] = []
    for name in names:
        if name not in STRATEGY_BUILDERS:
            continue
        structure = build_structure(name, chain, spot, T, r)
        if structure is None:
            continue
        ok, reasons = _legs_pass_filters(structure, filters)
        if not ok:
            continue
        liquidity = _liquidity_score(structure, max_spread)
        alignment = _alignment_score(structure, strength)
        rr = _risk_reward(structure)
        score = w_align * alignment + w_liq * liquidity + w_rr * min(1.0, rr / 3.0)
        candidates.append(Candidate(
            strategy=name, structure=structure, score=round(score, 4),
            liquidity=round(liquidity, 4), alignment=round(alignment, 4), risk_reward=round(rr, 4),
            rationale={
                "strength": strength, "regime": regime.value, "iv_rank": iv_rank,
                "net_greeks": structure.net_greeks, "max_loss": structure.max_loss,
                "max_profit": structure.max_profit, "breakevens": structure.breakevens,
            },
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
