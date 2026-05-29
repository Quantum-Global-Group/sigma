"""Volatility analytics — realized vol, IV rank/percentile, skew, spread.

Pure numpy. Formulas follow the Moomoo doc §4.3:
  Realized Vol = std(log returns) * sqrt(252)
  IV Rank      = (IV - 52w low) / (52w high - 52w low)
  Spread %     = (ask - bid) / mid
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

TRADING_DAYS = 252


def realized_vol(prices: Sequence[float], periods: int = TRADING_DAYS) -> float:
    """Annualized realized volatility from a price series (close-to-close)."""
    p = np.asarray(prices, dtype=float)
    p = p[p > 0]
    if len(p) < 3:
        return 0.0
    logret = np.diff(np.log(p))
    return float(np.std(logret, ddof=1) * np.sqrt(periods))


def iv_rank(current_iv: float, iv_history: Sequence[float]) -> float:
    """Where current IV sits in its [low, high] range over the history (0..1)."""
    h = np.asarray(iv_history, dtype=float)
    h = h[np.isfinite(h)]
    if len(h) == 0:
        return 0.0
    lo, hi = float(h.min()), float(h.max())
    if hi - lo < 1e-12:
        return 0.0
    return float(np.clip((current_iv - lo) / (hi - lo), 0.0, 1.0))


def iv_percentile(current_iv: float, iv_history: Sequence[float]) -> float:
    """Fraction of historical IV observations below the current IV (0..1)."""
    h = np.asarray(iv_history, dtype=float)
    h = h[np.isfinite(h)]
    if len(h) == 0:
        return 0.0
    return float(np.mean(h < current_iv))


def vol_skew(put_iv: float, call_iv: float) -> float:
    """Simple skew proxy: OTM-put IV minus OTM-call IV (positive = fear bid)."""
    return float(put_iv - call_iv)


def spread_pct(bid: float, ask: float) -> float:
    """Relative bid/ask spread vs mid. Returns inf for a non-positive mid."""
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return float("inf")
    return float((ask - bid) / mid)
