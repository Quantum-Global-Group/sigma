"""Monte-Carlo pricer for European-style payoffs (flexible payoff support).

Used as a cross-check on BS/binomial and for exotic/custom payoffs the closed
forms can't express. Antithetic variates reduce variance; seedable for tests.
"""

from __future__ import annotations

import math
from typing import Callable, Literal, Optional

import numpy as np

Right = Literal["call", "put"]


def mc_price(
    S: float, K: float, T: float, r: float, sigma: float,
    right: Right = "call", q: float = 0.0,
    n_paths: int = 100_000, seed: Optional[int] = 42,
    payoff: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> dict:
    """Monte-Carlo price of a terminal-payoff option under GBM.

    Returns {"price", "stderr"}. `payoff(ST)->array` overrides the vanilla
    call/put payoff for custom structures. Antithetic sampling is used.
    """
    if T <= 0:
        intrinsic = (S - K) if right == "call" else (K - S)
        return {"price": max(0.0, intrinsic), "stderr": 0.0}

    rng = np.random.default_rng(seed)
    half = max(1, n_paths // 2)
    z = rng.standard_normal(half)
    z = np.concatenate([z, -z])  # antithetic

    drift = (r - q - 0.5 * sigma * sigma) * T
    diffusion = sigma * math.sqrt(T) * z
    ST = S * np.exp(drift + diffusion)

    if payoff is not None:
        payoffs = payoff(ST)
    elif right == "call":
        payoffs = np.maximum(ST - K, 0.0)
    else:
        payoffs = np.maximum(K - ST, 0.0)

    disc = math.exp(-r * T)
    discounted = disc * payoffs
    price = float(discounted.mean())
    stderr = float(discounted.std(ddof=1) / math.sqrt(len(discounted)))
    return {"price": price, "stderr": stderr}
