"""Black-Scholes-Merton: European option price, analytic Greeks, and IV solver.

The European baseline (and the IV solver) for the options stack. American
early-exercise pricing lives in binomial_tree.py; for IV on US equity options
the BS approximation is standard and fast, and good enough for ranking/filters.
"""

from __future__ import annotations

import math
from typing import Literal

from scipy.optimize import brentq
from scipy.stats import norm

Right = Literal["call", "put"]


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        raise ValueError("S, K, T, sigma must be positive")
    vol_sqrt_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float, right: Right = "call", q: float = 0.0) -> float:
    """Black-Scholes price. `q` is the continuous dividend yield."""
    if T <= 0:
        intrinsic = (S - K) if right == "call" else (K - S)
        return max(0.0, intrinsic)
    if sigma <= 0:
        # Degenerate: discounted intrinsic forward.
        fwd = S * math.exp(-q * T) - K * math.exp(-r * T)
        return max(0.0, fwd if right == "call" else -fwd)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r, disc_q = math.exp(-r * T), math.exp(-q * T)
    if right == "call":
        return S * disc_q * norm.cdf(d1) - K * disc_r * norm.cdf(d2)
    return K * disc_r * norm.cdf(-d2) - S * disc_q * norm.cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, right: Right = "call", q: float = 0.0) -> dict:
    """Analytic Greeks. theta is per-year; vega/rho per 1.00 (100%) move —
    callers scale (vega/100 per 1 vol point, theta/365 per day) for display."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r, disc_q = math.exp(-r * T), math.exp(-q * T)
    pdf_d1 = norm.pdf(d1)
    sqrt_t = math.sqrt(T)

    gamma = disc_q * pdf_d1 / (S * sigma * sqrt_t)
    vega = S * disc_q * pdf_d1 * sqrt_t
    if right == "call":
        delta = disc_q * norm.cdf(d1)
        theta = (
            -S * disc_q * pdf_d1 * sigma / (2 * sqrt_t)
            - r * K * disc_r * norm.cdf(d2)
            + q * S * disc_q * norm.cdf(d1)
        )
        rho = K * T * disc_r * norm.cdf(d2)
    else:
        delta = -disc_q * norm.cdf(-d1)
        theta = (
            -S * disc_q * pdf_d1 * sigma / (2 * sqrt_t)
            + r * K * disc_r * norm.cdf(-d2)
            - q * S * disc_q * norm.cdf(-d1)
        )
        rho = -K * T * disc_r * norm.cdf(-d2)
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def implied_vol(
    price: float, S: float, K: float, T: float, r: float, right: Right = "call",
    q: float = 0.0, lo: float = 1e-4, hi: float = 5.0,
) -> float | None:
    """Solve BS for sigma given a market price. Returns None if no arbitrage-free
    solution exists in [lo, hi] (e.g. price below intrinsic or above bounds)."""
    if price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(0.0, (S - K) if right == "call" else (K - S))
    if price < intrinsic - 1e-9:
        return None

    def f(sigma: float) -> float:
        return bs_price(S, K, T, r, sigma, right, q) - price

    try:
        if f(lo) * f(hi) > 0:
            return None  # not bracketed
        return float(brentq(f, lo, hi, maxiter=100, xtol=1e-6))
    except (ValueError, RuntimeError):
        return None
