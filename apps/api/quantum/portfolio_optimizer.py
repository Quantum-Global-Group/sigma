"""
Portfolio optimization with classical (CVXPY MVO) and quantum (QAOA) backends.

`optimize()` is the single entrypoint. It dispatches to the chosen method and
falls back to MVO with `fallback=True` if quantum execution fails or times out.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import numpy as np
import pandas as pd

from ml.data import fetch_ohlcv
from quantum.qubo_solver import bitstring_to_weights, holdings_to_qubo, solve_qubo_qaoa

logger = logging.getLogger(__name__)

Method = Literal["mvo", "quantum_qaoa", "equal_weight"]


def _expected_returns_and_cov(tickers: list[str], lookback: str = "1y") -> tuple[np.ndarray, np.ndarray]:
    """Fetch historical returns for tickers, return (mu, Sigma) annualized."""
    closes: dict[str, pd.Series] = {}
    for t in tickers:
        try:
            df = fetch_ohlcv(t, "daily")
            closes[t] = df["close"]
        except Exception as exc:
            logger.warning("fetch_ohlcv failed for %s: %s", t, exc)
            raise ValueError(f"No data for ticker {t}")

    aligned = pd.DataFrame(closes).dropna()
    if aligned.empty or len(aligned) < 30:
        raise ValueError("Insufficient historical data for portfolio optimization")

    daily_returns = aligned.pct_change().dropna()
    mu = daily_returns.mean().values * 252  # annualized
    Sigma = daily_returns.cov().values * 252
    return mu, Sigma


def optimize_mvo(holdings: dict[str, float], risk_aversion: float = 1.0) -> dict:
    """Classical mean-variance optimization via CVXPY.

    Maximizes mu^T w - risk_aversion * w^T Sigma w subject to sum(w)=1, w >= 0.
    """
    import cvxpy as cp

    tickers = list(holdings.keys())
    mu, Sigma = _expected_returns_and_cov(tickers)
    n = len(tickers)

    w = cp.Variable(n, nonneg=True)
    objective = cp.Maximize(mu @ w - risk_aversion * cp.quad_form(w, cp.psd_wrap(Sigma)))
    constraints = [cp.sum(w) == 1]
    problem = cp.Problem(objective, constraints)
    problem.solve()

    if w.value is None:
        raise RuntimeError("MVO solver failed to converge")

    weights = np.array(w.value).clip(min=0)
    weights = weights / weights.sum() if weights.sum() > 0 else np.ones(n) / n

    expected_return = float(mu @ weights)
    variance = float(weights @ Sigma @ weights)
    sharpe = expected_return / np.sqrt(variance) if variance > 0 else 0.0

    return {
        "tickers": tickers,
        "weights": weights.tolist(),
        "sharpe_ratio": round(sharpe, 4),
        "expected_return": round(expected_return, 4),
    }


def optimize_qaoa(holdings: dict[str, float], risk_aversion: float = 1.0, depth: int = 2) -> dict:
    """Quantum portfolio selection via QAOA."""
    tickers = list(holdings.keys())
    if len(tickers) > 12:
        raise ValueError("QAOA optimizer supports at most 12 assets (qubit limit)")

    mu, Sigma = _expected_returns_and_cov(tickers)
    Q = holdings_to_qubo(mu, Sigma, risk_aversion=risk_aversion)

    bitstring = solve_qubo_qaoa(Q, depth=depth)
    weights = bitstring_to_weights(bitstring)

    expected_return = float(mu @ weights)
    variance = float(weights @ Sigma @ weights)
    sharpe = expected_return / np.sqrt(variance) if variance > 0 else 0.0

    return {
        "tickers": tickers,
        "weights": weights.tolist(),
        "sharpe_ratio": round(sharpe, 4),
        "expected_return": round(expected_return, 4),
    }


def optimize_equal_weight(holdings: dict[str, float]) -> dict:
    tickers = list(holdings.keys())
    n = len(tickers)
    weights = [1.0 / n] * n
    try:
        mu, Sigma = _expected_returns_and_cov(tickers)
        w = np.array(weights)
        sharpe = float(mu @ w) / float(np.sqrt(w @ Sigma @ w)) if w @ Sigma @ w > 0 else 0.0
    except Exception:
        sharpe = None
    return {"tickers": tickers, "weights": weights, "sharpe_ratio": round(sharpe, 4) if sharpe else None, "expected_return": None}


async def optimize(holdings: dict[str, float], method: Method = "mvo", risk_aversion: float = 1.0, timeout: float = 30.0) -> dict:
    """Top-level dispatcher.

    Returns a dict with keys: tickers, weights, target_allocation, recommended_trades,
    sharpe_ratio, method, fallback.
    """
    fallback = False
    actual_method = method

    try:
        if method == "quantum_qaoa":
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(optimize_qaoa, holdings, risk_aversion),
                    timeout=timeout,
                )
            except (asyncio.TimeoutError, ImportError, Exception) as exc:
                logger.warning("QAOA optimization failed (%s) — falling back to MVO", exc)
                fallback = True
                actual_method = "mvo"
                result = await asyncio.to_thread(optimize_mvo, holdings, risk_aversion)
        elif method == "equal_weight":
            result = await asyncio.to_thread(optimize_equal_weight, holdings)
        else:
            result = await asyncio.to_thread(optimize_mvo, holdings, risk_aversion)
    except Exception as exc:
        logger.error("Portfolio optimization failed: %s", exc)
        raise

    target_allocation = dict(zip(result["tickers"], result["weights"]))
    total_value = sum(holdings.values())
    recommended_trades = []
    for ticker, target_weight in target_allocation.items():
        target_value = total_value * target_weight
        current_value = holdings[ticker]
        delta = target_value - current_value
        if abs(delta) < 0.01 * total_value:  # ignore <1% changes
            continue
        recommended_trades.append({
            "ticker": ticker,
            "action": "BUY" if delta > 0 else "SELL",
            "amount": round(abs(delta), 2),
        })

    return {
        "method": actual_method,
        "fallback": fallback,
        "target_allocation": {k: round(v, 4) for k, v in target_allocation.items()},
        "recommended_trades": recommended_trades,
        "sharpe_ratio": result.get("sharpe_ratio"),
    }
