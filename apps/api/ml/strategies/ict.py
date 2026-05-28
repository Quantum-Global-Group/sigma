"""ICT (Inner Circle Trader) concepts strategy.

Ported from tradeFlux core/ict_strategy.py (itself ported from LuxAlgo's
"ICT Concepts" Pine Script, CC BY-NC-SA 4.0). Implements Market Structure
Shift (MSS), Fair Value Gaps (FVG), and Order Blocks (OB).

The source produced a full signal Series; this adapts to sigma's per-symbol
contract by computing over the trailing window and reading the latest bar,
grading confidence by how many ICT confluences (structure + FVG + OB) align."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseStrategy, Signal


def _pivot_high(high: pd.Series, left: int, right: int = 1) -> pd.Series:
    out = pd.Series(False, index=high.index)
    for i in range(left, len(high) - right):
        window = high.iloc[i - left: i + right + 1]
        if high.iloc[i] == window.max() and window.idxmax() == high.index[i]:
            out.iloc[i] = True
    return out


def _pivot_low(low: pd.Series, left: int, right: int = 1) -> pd.Series:
    out = pd.Series(False, index=low.index)
    for i in range(left, len(low) - right):
        window = low.iloc[i - left: i + right + 1]
        if low.iloc[i] == window.min() and window.idxmin() == low.index[i]:
            out.iloc[i] = True
    return out


def _detect_swings(high, low, length):
    ph = _pivot_high(high, length, 1)
    pl = _pivot_low(low, length, 1)
    swing_high = pd.Series(np.nan, index=high.index)
    swing_low = pd.Series(np.nan, index=low.index)
    direction = pd.Series(0, index=high.index, dtype=float)
    last_high = last_low = np.nan
    last_dir = 0
    for i in range(length, len(high) - 1):
        if ph.iloc[i]:
            last_high, last_dir = high.iloc[i], 1
        if pl.iloc[i]:
            last_low, last_dir = low.iloc[i], -1
        swing_high.iloc[i] = last_high
        swing_low.iloc[i] = last_low
        direction.iloc[i] = last_dir
    return swing_high, swing_low, direction


def _detect_fvg(open_, high, low, close, use_body):
    body_up = close > open_
    body_dn = close < open_
    bull_top = pd.Series(np.nan, index=high.index)
    bull_btm = pd.Series(np.nan, index=high.index)
    bear_top = pd.Series(np.nan, index=high.index)
    bear_btm = pd.Series(np.nan, index=high.index)
    for i in range(2, len(high)):
        mx_2 = max(open_.iloc[i - 2], close.iloc[i - 2]) if use_body else high.iloc[i - 2]
        mn_2 = min(open_.iloc[i - 2], close.iloc[i - 2]) if use_body else low.iloc[i - 2]
        if body_up.iloc[i - 1] and low.iloc[i] > mx_2:
            bull_btm.iloc[i], bull_top.iloc[i] = mx_2, low.iloc[i]
        if body_dn.iloc[i - 1] and high.iloc[i] < mn_2:
            bear_top.iloc[i], bear_btm.iloc[i] = mn_2, high.iloc[i]
    return bull_top, bull_btm, bear_top, bear_btm


class ICTStrategy(BaseStrategy):
    def __init__(self, swing_length: int = 5, use_body: bool = True, max_bars: int = 240) -> None:
        super().__init__("ict")
        self.swing_length = swing_length
        self.use_body = use_body
        self.max_bars = max_bars  # cap the window so per-tick cost stays bounded

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        data = features.iloc[-self.max_bars:]
        high = pd.to_numeric(data["h"], errors="coerce")
        low = pd.to_numeric(data["l"], errors="coerce")
        open_ = pd.to_numeric(data["o"], errors="coerce")
        close = pd.to_numeric(data["c"], errors="coerce")
        length = max(3, min(10, int(self.swing_length)))
        if len(data) < length + 3 or high.isna().all():
            return Signal(0.0, 0.0, self.name)

        swing_high, swing_low, direction = _detect_swings(high, low, length)
        bull_t, bull_b, bear_t, bear_b = _detect_fvg(open_, high, low, close, self.use_body)

        # Market-structure shift at the latest bar.
        i = len(data) - 2  # last fully-formed bar (mirrors source range)
        mss_bull = mss_bear = False
        if i > length:
            if direction.iloc[i - 1] == -1 and not np.isnan(swing_high.iloc[i - 1]) and close.iloc[i] > swing_high.iloc[i - 1]:
                mss_bull = True
            if direction.iloc[i - 1] == 1 and not np.isnan(swing_low.iloc[i - 1]) and close.iloc[i] < swing_low.iloc[i - 1]:
                mss_bear = True

        # Is the latest close inside a bull/bear FVG?
        in_bull_fvg = _in_latest_gap(close, bull_b, bull_t)
        in_bear_fvg = _in_latest_gap(close, bear_b, bear_t)

        bull = mss_bull or (direction.iloc[i] == 1 if i < len(direction) else False)
        bear = mss_bear or (direction.iloc[i] == -1 if i < len(direction) else False)

        strength = 0.0
        confluence = 0
        if bull and not bear:
            confluence = int(mss_bull) + int(in_bull_fvg)
            strength = 1.0 if (in_bull_fvg or mss_bull) else 0.5
        elif bear and not bull:
            confluence = int(mss_bear) + int(in_bear_fvg)
            strength = -1.0 if (in_bear_fvg or mss_bear) else -0.5

        confidence = min(1.0, 0.4 + 0.3 * confluence)
        if strength == 0.0:
            confidence = 0.0
        return Signal(strength, float(confidence), self.name,
                      metadata={"mss_bull": mss_bull, "mss_bear": mss_bear,
                                "in_bull_fvg": bool(in_bull_fvg), "in_bear_fvg": bool(in_bear_fvg)})


def _in_latest_gap(close: pd.Series, btm: pd.Series, top: pd.Series) -> bool:
    """Whether the latest close sits inside the most recent FVG band."""
    last_b = last_t = np.nan
    for i in range(2, len(close)):
        if not np.isnan(btm.iloc[i]):
            last_b, last_t = btm.iloc[i], top.iloc[i]
    if np.isnan(last_b) or last_b == last_t:
        return False
    lo, hi = min(last_b, last_t), max(last_b, last_t)
    return bool(lo <= close.iloc[-1] <= hi)
