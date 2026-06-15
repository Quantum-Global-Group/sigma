#!/usr/bin/env python
"""The four surviving ideas, combined into ONE retail portfolio — and judged.

Everything market-neutral failed. What survived the cross-regime bar was
risk-managed beta. This assembles the four ideas that passed into a single,
fully-implementable strategy and backtests it honestly (2005–2026, incl. 2008 /
2020 / 2022) against what a retail investor would otherwise do — hold SPY, or a
classic 60/40.

Strategy "Diversified + Trend":
  1. Diversify across uncorrelated sleeves (US/intl equity, bonds, gold,
     commodities, REIT, a little crypto) at a FIXED, un-optimized allocation.
  2. Trend-filter each sleeve: hold the asset only when it's above its
     10-month moving average; otherwise that sleeve sits in cash (SHY).
  3. Rebalance monthly — low turnover, the only horizon that survived costs.
  4. + a small TSMOM crisis sleeve (long/short trend of the universe) that can
     PROFIT in crashes, not just sidestep them (the "+crisis" variant).

Lookahead-safe (signal at month t from data ≤ t, earns t+1), net of a 5bps
turnover cost. Conclusion = CAGR / Sharpe / maxDD / crisis-year returns vs
benchmarks.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/retail_portfolio_backtest.py
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets import get_market_adapter

logging.basicConfig(level=logging.WARNING)

START = "2005-01-01"
COST = 5.0 / 1e4
MA = 10
CASH = "SHY"            # cash proxy (1–3y treasuries) for "out" sleeves

# One-Alpaca-account allocation: every sleeve is an Alpaca-tradeable ETF, incl.
# currencies (UUP/FXE — no OANDA needed) and Bitcoin (IBIT in production; the
# backtest uses BTC-USD as the price proxy since IBIT only lists from 2024).
# Fixed, un-optimized weights — the method matters, not the exact split.
SLEEVES = {
    "SPY": 0.28, "EFA": 0.08, "EEM": 0.04,     # equity 40%
    "TLT": 0.13, "IEF": 0.10,                   # bonds 23%
    "GLD": 0.10, "DBC": 0.05,                   # real assets 15%
    "VNQ": 0.05,                                # reit 5%
    "UUP": 0.05, "FXE": 0.03,                   # currencies via ETFs 8% (no OANDA)
    "BTC-USD": 0.04,                            # Bitcoin 4% (IBIT live; BTC proxy here)
}


def _deep_crypto_daily(symbol, days=4000):
    adapter = get_market_adapter("crypto")
    rows = adapter._fetch_paginated(adapter.normalize_symbol(symbol),
                                    adapter._now() - timedelta(days=days), adapter._now(), 86400)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    return df.drop_duplicates("ts").sort_values("ts").set_index("ts").astype(float)


_PX_CACHE = "/tmp/sigma_monthly_px"


def monthly_close(symbol):
    """Monthly close series, disk-cached per symbol so reruns don't re-hit the
    (rate-limited) Tiingo free tier and partial progress persists."""
    import json
    import time
    os.makedirs(_PX_CACHE, exist_ok=True)
    path = os.path.join(_PX_CACHE, f"{symbol.replace('/', '_')}.json")
    if os.path.exists(path):
        d = json.load(open(path))
        if d:
            return pd.Series({pd.Timestamp(k): v for k, v in d.items()})  # tz-naive
    if symbol.endswith("-USD"):
        df = _deep_crypto_daily(symbol)
    else:
        from markets.equity_data import fetch_tiingo
        df = None
        for attempt in range(5):                 # Tiingo 429 — patient backoff
            df = fetch_tiingo(symbol, "daily", start=START)
            if df is not None and len(df) >= 60:
                break
            time.sleep(8 * (attempt + 1))
    if df is None or len(df) < 60:
        return None
    m = df["close"].astype(float).resample("ME").last()
    if getattr(m.index, "tz", None) is not None:
        m.index = m.index.tz_localize(None)   # match the tz-naive cache path
    json.dump({str(k.date()): float(v) for k, v in m.items() if pd.notna(v)}, open(path, "w"))
    return m


def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    n = len(r)
    cagr = eq.iloc[-1] ** (12 / n) - 1
    vol = r.std() * np.sqrt(12)
    sharpe = (r.mean() / r.std() * np.sqrt(12)) if r.std() > 0 else 0.0
    dd = (eq / eq.cummax() - 1).min()
    by_year = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
    return {
        "CAGR%": cagr * 100, "vol%": vol * 100, "Sharpe": sharpe, "maxDD%": dd * 100,
        "2008%": by_year.get(2008, np.nan) * 100, "2020%": by_year.get(2020, np.nan) * 100,
        "2022%": by_year.get(2022, np.nan) * 100,
    }


def main():
    print("fetching sleeves + cash (deep history) …")
    px = {}
    for s in list(SLEEVES) + [CASH, "QQQ"]:
        m = monthly_close(s)
        if m is not None:
            px[s] = m
    P = pd.DataFrame(px)
    rets = P.pct_change()
    rets = rets[rets.index >= START]
    if CASH in rets:
        cash_r = rets[CASH].fillna(0.0)
    else:
        print(f"  WARN: {CASH} unavailable — using a flat ~1.8%/yr cash proxy")
        cash_r = pd.Series(0.0015, index=rets.index)
    n_assets = [s for s in SLEEVES if s in rets]
    print(f"  {len(n_assets)} sleeves, {len(rets)} months ({rets.index.min():%Y-%m} … {rets.index.max():%Y-%m})")

    # trend signal per sleeve (lookahead-safe: formed at t, earns t+1)
    sig = {}
    for s in n_assets:
        p = P[s]
        sig[s] = (p > p.rolling(MA).mean()).astype(float)
    sig = pd.DataFrame(sig)

    def portfolio(weights: dict, trend: bool):
        total = sum(weights[s] for s in n_assets)
        w = {s: weights[s] / total for s in n_assets}
        pnl = pd.Series(0.0, index=rets.index)
        prev_in = {s: 0.0 for s in n_assets}
        for s in n_assets:
            in_mkt = sig[s].shift(1).fillna(0.0) if trend else pd.Series(1.0, index=rets.index)
            sleeve = w[s] * (in_mkt * rets[s].fillna(cash_r) + (1 - in_mkt) * cash_r)
            # turnover cost when the sleeve flips in/out of market
            flips = in_mkt.diff().abs().fillna(0.0)
            sleeve = sleeve - w[s] * flips * COST
            pnl = pnl.add(sleeve, fill_value=0.0)
        return pnl

    # TSMOM crisis sleeve: long/short sign of 12m return across the universe
    cum12 = (1 + rets[n_assets]).rolling(12).apply(np.prod, raw=True) - 1
    tsmom = (np.sign(cum12).shift(1) * rets[n_assets]).mean(axis=1, skipna=True)

    eqw = {s: 1.0 for s in n_assets}
    results = {
        "SPY buy&hold": rets["SPY"],
        "60/40 (SPY/TLT)": 0.6 * rets["SPY"] + 0.4 * rets["TLT"],
        "Diversified buy&hold": portfolio(SLEEVES, trend=False),
        "Diversified + Trend": portfolio(SLEEVES, trend=True),
        "Equal-wt + Trend": portfolio(eqw, trend=True),
        "Div+Trend +10% crisis": 0.9 * portfolio(SLEEVES, trend=True) + 0.1 * tsmom,
    }

    cols = ["CAGR%", "vol%", "Sharpe", "maxDD%", "2008%", "2020%", "2022%"]
    print(f"\n  {'strategy':<24}" + "".join(f"{c:>9}" for c in cols))
    for name, r in results.items():
        m = metrics(r)
        print(f"  {name:<24}" + "".join(
            f"{m[c]:>9.1f}" if c != "Sharpe" else f"{m[c]:>9.2f}" for c in cols))

    print("\n  Read: the four ideas combined ('Diversified + Trend') vs just holding SPY")
    print("  or 60/40 — compare Sharpe AND maxDD AND the 2008/2022 crisis columns.")


if __name__ == "__main__":
    main()
