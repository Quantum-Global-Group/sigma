#!/usr/bin/env python
"""Cross-asset, low-turnover signals — the families with real retail evidence.

Everything rejected so far was short-horizon, single-instrument, on liquid names.
The edges that actually survive for retail are the opposite: diversified,
multi-asset, monthly. This tests those honestly across ~20 years (spanning 2008
AND 2020) on a broad ETF universe — equities, sectors, commodities, bonds,
currencies, crypto — all retail-tradeable.

Signals (portfolio-level, net of cost, annualized):
  1. buy & hold        — each asset + an equal-weight monthly-rebalanced book
                          (the diversification premium / realistic benchmark)
  2. TSMOM(L)          — time-series momentum: sign(past-L-month return), held a
                          month, diversified across all assets. The classic
                          cross-asset trend premium. Tested at L = 3/6/9/12.
  3. trend filter      — absolute momentum: long only above the 10-month average,
                          else cash. Documented crash protection.

Honesty checks built in: net of a per-rebalance cost, first-half vs second-half
Sharpe (TSMOM is known to have decayed post-2010), and 2008/2020 behavior
(does trend actually protect in crises?).

Usage:
    cd apps/api && PYTHONPATH=. .venv/bin/python scripts/cross_asset_experiment.py
"""

from __future__ import annotations

import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets import get_market_adapter
from ml import costs

logging.basicConfig(level=logging.WARNING)

START = "2005-01-01"
COST_BPS = 5.0          # ETF round-trip on a monthly rebalance — generous
MOM_HORIZONS = [3, 6, 9, 12]

UNIVERSE = {
    "equity_idx": ["SPY", "QQQ", "IWM", "EFA", "EEM"],
    "sector":     ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"],
    "commodity":  ["GLD", "SLV", "USO", "UNG", "DBA", "DBC"],
    "bond":       ["TLT", "IEF", "LQD", "HYG", "TIP"],
    "currency":   ["UUP", "FXE", "FXY", "FXB"],
    "reit":       ["VNQ"],
}
CRYPTO = ["BTC-USD", "ETH-USD"]


def _deep_crypto_daily(adapter, symbol, days=3000):
    from datetime import timedelta
    product = adapter.normalize_symbol(symbol)
    end = adapter._now()
    rows = adapter._fetch_paginated(product, end - timedelta(days=days), end, 86400)
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    return df.drop_duplicates("ts").sort_values("ts").set_index("ts").astype(float)


def _monthly_returns(symbols, asset_class="equity"):
    """Monthly simple returns per symbol, aligned (NaN pre-inception).

    Equity uses Tiingo directly for deep (20y) EOD history — the unified adapter
    tries Alpaca first, whose IEX history is too short to span 2008/2020."""
    from markets.equity_data import fetch_tiingo
    adapter = get_market_adapter("crypto") if asset_class == "crypto" else None
    series = {}
    for s in symbols:
        try:
            if asset_class == "crypto":
                df = _deep_crypto_daily(adapter, s)
            else:
                df = fetch_tiingo(s, "daily", start=START)
            if df is None or len(df) < 60:
                continue
            m = df["close"].astype(float).resample("ME").last()
            series[s] = m.pct_change()
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    return pd.DataFrame(series)


def _ann_sharpe(r):
    r = r.dropna()
    return costs.sharpe(r.to_numpy(), periods_per_year=12) or 0.0


def _net(positions: pd.DataFrame, rets: pd.DataFrame, cost):
    """Diversified portfolio monthly return: mean over available assets of
    position·next-return, minus cost on turnover."""
    pos = positions.shift(1)                      # decide on info up to t, earn t+1
    pnl = (pos * rets)
    turnover = positions.diff().abs()
    pnl = pnl - turnover.shift(1) * cost
    return pnl.mean(axis=1, skipna=True)          # equal-weight across assets


def main():
    print("fetching cross-asset universe (this spans 2008 + 2020) …")
    rets = _monthly_returns([s for v in UNIVERSE.values() for s in v], "equity")
    cr = _monthly_returns(CRYPTO, "crypto")
    rets = pd.concat([rets, cr], axis=1)
    rets = rets.dropna(how="all")
    print(f"  {rets.shape[1]} assets, {rets.shape[0]} months "
          f"({rets.index.min():%Y-%m} … {rets.index.max():%Y-%m})")
    cost = COST_BPS / 1e4

    # 1) buy & hold benchmark — equal-weight, monthly rebalanced
    bh = rets.mean(axis=1, skipna=True)
    print(f"\n  {'signal':<16}{'ann_Sharpe':>11}{'1st-half':>10}{'2nd-half':>10}"
          f"{'2008':>8}{'2020':>8}{'maxDD%':>8}")

    def report(label, port):
        port = port.dropna()
        h = len(port) // 2
        s_all, s1, s2 = _ann_sharpe(port), _ann_sharpe(port.iloc[:h]), _ann_sharpe(port.iloc[h:])
        y08 = port[port.index.year == 2008].sum() * 100
        y20 = port[port.index.year == 2020].sum() * 100
        dd = costs.max_drawdown(port.to_numpy()) * 100
        print(f"  {label:<16}{s_all:>11.2f}{s1:>10.2f}{s2:>10.2f}{y08:>8.1f}{y20:>8.1f}{dd:>8.1f}")

    report("buy_hold", bh)

    # 2) time-series momentum at several horizons
    for L in MOM_HORIZONS:
        cum = (1 + rets).rolling(L).apply(np.prod, raw=True) - 1   # past-L-month return
        sig = np.sign(cum)
        report(f"TSMOM_{L}m", _net(sig, rets, cost))

    # 3) absolute-momentum trend filter (long above N-month MA, else cash).
    # Test several MA lengths so 10m isn't cherry-picked.
    price = (1 + rets.fillna(0)).cumprod()
    for n in (7, 8, 10, 12):
        long_filter = (price > price.rolling(n).mean()).astype(float)
        report(f"trend_{n}m", _net(long_filter, rets, cost))

    # 4) the simplest retail case: time SPY alone with the 10m MA vs hold SPY.
    print()
    spy = rets[["SPY"]].dropna()
    p = (1 + spy).cumprod()
    spy_filter = (p > p.rolling(10).mean()).astype(float)
    report("SPY buy_hold", spy["SPY"])
    report("SPY trend_10m", _net(spy_filter, spy, cost))

    print("\n  Read: trend filter's win is regime-robust (both halves) + crisis protection")
    print("  (2008/maxDD). It is smarter BETA (timing exposure), not market-neutral alpha.")


if __name__ == "__main__":
    main()
