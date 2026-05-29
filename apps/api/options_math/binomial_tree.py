"""Cox-Ross-Rubinstein binomial tree — American (and European) option pricing.

US equity options are American (early exercise allowed), which BS cannot price.
The CRR tree handles early exercise; Greeks are taken by finite difference off
the tree so callers get an American-consistent risk profile.
"""

from __future__ import annotations

import math
from typing import Literal

Right = Literal["call", "put"]


def binomial_price(
    S: float, K: float, T: float, r: float, sigma: float,
    right: Right = "call", q: float = 0.0, steps: int = 200, american: bool = True,
) -> float:
    """CRR binomial price. `american=True` allows early exercise at each node."""
    if T <= 0:
        intrinsic = (S - K) if right == "call" else (K - S)
        return max(0.0, intrinsic)
    if steps < 1:
        steps = 1

    dt = T / steps
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    disc = math.exp(-r * dt)
    # Risk-neutral up-probability with continuous dividend yield q.
    p = (math.exp((r - q) * dt) - d) / (u - d)
    if not (0.0 <= p <= 1.0):
        # Numerical/degenerate params — clamp to keep it well-defined.
        p = min(1.0, max(0.0, p))

    # Terminal payoffs.
    values = []
    for i in range(steps + 1):
        ST = S * (u ** (steps - i)) * (d ** i)
        payoff = (ST - K) if right == "call" else (K - ST)
        values.append(max(0.0, payoff))

    # Backward induction.
    for step in range(steps - 1, -1, -1):
        for i in range(step + 1):
            cont = disc * (p * values[i] + (1.0 - p) * values[i + 1])
            if american:
                ST = S * (u ** (step - i)) * (d ** i)
                exercise = (ST - K) if right == "call" else (K - ST)
                values[i] = max(cont, exercise)
            else:
                values[i] = cont
    return float(values[0])


def binomial_greeks(
    S: float, K: float, T: float, r: float, sigma: float,
    right: Right = "call", q: float = 0.0, steps: int = 200, american: bool = True,
) -> dict:
    """Finite-difference Greeks off the binomial tree (American-consistent)."""
    h = max(1e-4, S * 1e-3)
    base = binomial_price(S, K, T, r, sigma, right, q, steps, american)
    up = binomial_price(S + h, K, T, r, sigma, right, q, steps, american)
    dn = binomial_price(S - h, K, T, r, sigma, right, q, steps, american)
    delta = (up - dn) / (2 * h)
    gamma = (up - 2 * base + dn) / (h * h)

    dv = 1e-3
    vega = (binomial_price(S, K, T, r, sigma + dv, right, q, steps, american) - base) / dv
    dr = 1e-4
    rho = (binomial_price(S, K, T, r + dr, sigma, right, q, steps, american) - base) / dr
    dt = min(1.0 / 365.0, T / 2)
    theta = (binomial_price(S, K, T - dt, r, sigma, right, q, steps, american) - base) / dt if T > dt else 0.0

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}
