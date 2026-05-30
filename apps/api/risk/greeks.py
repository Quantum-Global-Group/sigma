"""Portfolio-level Greeks aggregation, limits, and delta hedging (doc §6.3).

The optimizer should know the book's net Δ/Γ/Θ/Vega and recommend a hedge
*before* adding new option exposure. Pure functions over leg/structure Greeks
so they're trivially testable and broker-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class GreekLimits:
    max_abs_net_delta: float = 0.0   # in share-equivalents; 0 disables
    max_abs_net_gamma: float = 0.0
    max_abs_net_vega: float = 0.0


@dataclass(frozen=True)
class GreekExposure:
    delta: float
    gamma: float
    theta: float
    vega: float

    def as_dict(self) -> dict:
        return {"delta": self.delta, "gamma": self.gamma, "theta": self.theta, "vega": self.vega}


def aggregate_greeks(positions: Iterable[dict]) -> GreekExposure:
    """Sum position Greeks into a net book exposure.

    Each position is {"greeks": {delta,gamma,theta,vega}, "qty": float,
    "multiplier": int(=100)}. `qty` is signed (long +, short -). The returned
    figures are per-share-equivalent × multiplier (i.e. contract-scaled).
    """
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for pos in positions:
        g = pos.get("greeks", {})
        qty = float(pos.get("qty", 0.0))
        mult = float(pos.get("multiplier", 100))
        for k in net:
            net[k] += float(g.get(k, 0.0)) * qty * mult
    return GreekExposure(**net)


def check_greek_limits(net: GreekExposure, limits: GreekLimits) -> tuple[bool, list[str]]:
    """Return (ok, breaches). A limit of 0 disables that check."""
    breaches: list[str] = []
    if limits.max_abs_net_delta and abs(net.delta) > limits.max_abs_net_delta:
        breaches.append(f"net delta {net.delta:.1f} exceeds {limits.max_abs_net_delta}")
    if limits.max_abs_net_gamma and abs(net.gamma) > limits.max_abs_net_gamma:
        breaches.append(f"net gamma {net.gamma:.2f} exceeds {limits.max_abs_net_gamma}")
    if limits.max_abs_net_vega and abs(net.vega) > limits.max_abs_net_vega:
        breaches.append(f"net vega {net.vega:.1f} exceeds {limits.max_abs_net_vega}")
    return (len(breaches) == 0, breaches)


@dataclass(frozen=True)
class HedgeRecommendation:
    shares: float          # signed: + = buy underlying, - = sell/short underlying
    side: str              # "buy" | "sell" | "none"
    reason: str


def delta_hedge(net_delta: float, *, tolerance: float = 1.0) -> HedgeRecommendation:
    """Recommend an underlying-share trade to flatten net delta.

    net_delta is in share-equivalents (already contract-scaled). To neutralize a
    positive (long) delta you SELL that many shares, and vice-versa.
    """
    if abs(net_delta) <= tolerance:
        return HedgeRecommendation(0.0, "none", "within delta tolerance")
    shares = -net_delta
    side = "buy" if shares > 0 else "sell"
    return HedgeRecommendation(round(shares, 2), side, f"flatten net delta {net_delta:.1f}")
