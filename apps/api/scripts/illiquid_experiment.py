#!/usr/bin/env python
"""Thesis 3 — less-liquid technical. Cheapest check, lowest prior.

The per-strategy sweep showed technical signals are coin-flips on liquid names.
The one remaining hope is that edge survives longer in less-efficient (smaller)
names — but illiquidity also means WIDER spreads, which is exactly what eats the
edge. This measures the blend that would actually trade, on a small/mid-cap
universe, at a realistic round-trip cost (default 25 bps, vs 2 bps for mega-caps).

Honest-cost is the crux: a too-low cost manufactures fake edge. The verdict is
net-of-cost per-bar return + Sharpe of the equal-weight blend (what the worker
trades) and buy & hold, over a 2-year daily window.

Usage:
    cd apps/api && PYTHONPATH=. .venv/bin/python scripts/illiquid_experiment.py
    PYTHONPATH=. .venv/bin/python scripts/illiquid_experiment.py --cost-bps 40
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets.equity_data import fetch_equity_ohlcv
from ml import costs
from ml.sequences import FeatureEngineer
from ml.strategies.combiner import build_default_combiner

logging.basicConfig(level=logging.WARNING)

THRESHOLD = 0.1
LOOKBACK = 160
# Small/mid-cap, higher-volatility names with Alpaca/Tiingo coverage. Liquid
# enough to have clean data, far less efficient than mega-caps.
UNIVERSE = ["ETSY", "ROKU", "DKNG", "PINS", "RBLX", "AFRM", "UPST", "CHWY",
            "PLUG", "RIOT", "FUBO", "SOFI", "LYFT", "SNAP", "W", "BYND"]


def blend_net(fe, combiner, cost_frac, warmup=50):
    close = fe["c"].to_numpy(dtype=float)
    n = len(fe)
    pos = np.zeros(n)
    for t in range(warmup, n):
        try:
            s = float(combiner.combine_signals("SYM", fe.iloc[max(0, t - LOOKBACK):t + 1],
                                               float(close[t])).strength)
        except Exception:
            s = 0.0
        pos[t] = 1.0 if s > THRESHOLD else (-1.0 if s < -THRESHOLD else 0.0)
    pos, ret = pos[:-1], (close[1:] / np.where(close[:-1] != 0, close[:-1], 1.0) - 1.0)
    flips = np.abs(np.diff(np.concatenate([[0.0], pos]))) > 1e-9
    net = pos * ret - flips * cost_frac
    bh = ret.copy()   # buy & hold benchmark
    return net, bh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=25.0)
    ap.add_argument("--symbols", nargs="+", default=UNIVERSE)
    args = ap.parse_args()
    cf = args.cost_bps / 1e4

    combiner = build_default_combiner("equity")
    fe_engine = FeatureEngineer()
    blend_all, bh_all, kept = [], [], 0
    for s in args.symbols:
        try:
            df = fetch_equity_ohlcv(s, "daily")
            fe = fe_engine.compute(df)
            if len(fe) > LOOKBACK + 80:
                net, bh = blend_net(fe, combiner, cf)
                blend_all.append(net); bh_all.append(bh); kept += 1
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    if not blend_all:
        print("no data"); return
    net = np.concatenate(blend_all); bh = np.concatenate(bh_all)

    print(f"\n=== less-liquid technical: {kept} small/mid-caps, {len(net)} bars, "
          f"cost {args.cost_bps:.0f}bps round-trip ===")
    for label, series in [("BLEND (net)", net), ("buy_hold", bh)]:
        sh = costs.sharpe(series, 252) or 0.0
        print(f"  {label:<14} net_bps/bar {series.mean()*1e4:>7.2f}  sharpe {sh:>6.2f}  "
              f"total {series.sum()*100:>8.1f}%  maxDD {costs.max_drawdown(series)*100:>6.1f}%")
    blend_sh = costs.sharpe(net, 252) or 0.0
    ok = net.mean() > 0 and blend_sh > 0
    print(f"  VERDICT: less-liquid blend {'PASS' if ok else 'REJECT'} "
          f"(net {net.mean()*1e4:.2f} bps/bar, Sharpe {blend_sh:.2f}).")


if __name__ == "__main__":
    main()
