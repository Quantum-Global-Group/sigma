"""Unified Greeks container + model dispatch.

`greeks(...)` picks the analytic BS Greeks (fast, European) or the
finite-difference binomial Greeks (American-consistent) and returns a typed
`Greeks` dataclass with display-friendly scaling helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .black_scholes import bs_greeks
from .binomial_tree import binomial_greeks

Right = Literal["call", "put"]
Model = Literal["bs", "binomial"]


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta: float   # per-year
    vega: float    # per 1.00 (100%) vol move
    rho: float     # per 1.00 (100%) rate move

    @property
    def theta_per_day(self) -> float:
        return self.theta / 365.0

    @property
    def vega_per_vol_point(self) -> float:
        """Vega per 1 percentage-point change in IV (the trader-readable form)."""
        return self.vega / 100.0

    def as_dict(self) -> dict:
        return {
            "delta": self.delta, "gamma": self.gamma, "theta": self.theta,
            "vega": self.vega, "rho": self.rho,
            "theta_per_day": self.theta_per_day,
            "vega_per_vol_point": self.vega_per_vol_point,
        }


def greeks(
    S: float, K: float, T: float, r: float, sigma: float,
    right: Right = "call", q: float = 0.0, model: Model = "bs",
) -> Greeks:
    raw = (
        binomial_greeks(S, K, T, r, sigma, right, q)
        if model == "binomial"
        else bs_greeks(S, K, T, r, sigma, right, q)
    )
    return Greeks(
        delta=raw["delta"], gamma=raw["gamma"], theta=raw["theta"],
        vega=raw["vega"], rho=raw["rho"],
    )
