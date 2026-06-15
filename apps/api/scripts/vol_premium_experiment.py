#!/usr/bin/env python
"""Options edge — the volatility risk premium, honestly (incl. the tail).

Directional edge is dead in equities/crypto/FX (measured). The one untested
asset class with a *structural* edge is options: implied volatility systematically
exceeds realized, so SELLING option premium has positive expected return. The
cleanest tradeable proxy with deep history is shorting VXX (a long-VIX-futures
ETF that bleeds ~the premium): being short it = collecting what option-sellers
collect.

The whole point is to measure BOTH sides honestly:
  * the premium  — short-vol's calm-period return / Sharpe
  * the TAIL     — its drawdown in vol spikes (2018 'Volmageddon', 2020 COVID).
    Naked short vol blew up XIV in Feb-2018 (-90% in a day). A premium you can't
    survive collecting is not an edge.

Also tests a trend-filtered short-vol (short only while VXX is below its 50-day
MA — i.e. vol falling), to see whether the same risk-management that saved the
allocation tames the tail here too.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/vol_premium_experiment.py
"""

from __future__ import annotations

import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)

START = "2009-02-01"
COST = 5.0 / 1e4          # per round-trip on the trend-filter flips
BORROW = 0.03 / 252       # ~3%/yr short-borrow drag on VXX, daily
MA_DAYS = 50


def daily_close(symbol):
    from markets.equity_data import fetch_tiingo
    df = fetch_tiingo(symbol, "daily", start=START)
    return df["close"].astype(float) if df is not None and len(df) > 200 else None


def stats(r: pd.Series, label: str):
    r = r.dropna()
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (252 / len(r)) - 1
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    dd = (eq / eq.cummax() - 1).min()
    worst = r.min()
    by_year = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
    y18, y20, y22 = (by_year.get(y, np.nan) * 100 for y in (2018, 2020, 2022))
    print(f"  {label:<22}{cagr*100:>9.1f}{sharpe:>9.2f}{dd*100:>9.1f}{worst*100:>9.1f}"
          f"{y18:>8.1f}{y20:>8.1f}{y22:>8.1f}")


def main():
    vxx = daily_close("VXX")
    if vxx is None:
        print("no VXX data"); return
    vret = vxx.pct_change()
    print(f"VXX {len(vxx)} days ({vxx.index.min():%Y-%m} … {vxx.index.max():%Y-%m})")
    print(f"  VXX long total return: {((1+vret.fillna(0)).prod()-1)*100:.0f}%  "
          f"(this much value lost to the premium = what a short collects)")

    print(f"\n  {'strategy':<22}{'CAGR%':>9}{'Sharpe':>9}{'maxDD%':>9}{'worstday%':>9}"
          f"{'2018':>8}{'2020':>8}{'2022':>8}")

    # 1) naked short vol — hold the short (collect the premium, eat the tail)
    short = -vret - BORROW
    stats(short, "short vol (naked)")

    # 2) trend-filtered short vol — short only while VXX < its 50d MA (vol falling)
    ma = vxx.rolling(MA_DAYS).mean()
    pos = (vxx < ma).astype(float).shift(1).fillna(0.0)    # decide t, earn t+1
    flips = pos.diff().abs().fillna(0.0)
    tf = pos * (-vret) - pos * BORROW - flips * COST
    stats(tf, "short vol + trend")

    # 3) SPY benchmark for context
    spy = daily_close("SPY")
    if spy is not None:
        stats(spy.pct_change(), "SPY buy&hold")

    print("\n  Read: naked short-vol's CAGR/Sharpe is the premium; its maxDD/worstday")
    print("  is the tail (a single day can wipe years of premium). Does the trend")
    print("  filter keep the premium while cutting the tail?")


if __name__ == "__main__":
    main()
