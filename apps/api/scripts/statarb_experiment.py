#!/usr/bin/env python
"""Thesis 2 — relative-value / stat-arb. Market-neutral, different in KIND.

Not directional (so not the dead price-direction game) and explicitly NOT the
cross-sectional ranking already rejected. For each economically-related pair we
fit a hedge ratio + spread distribution on the EARLIER data, then trade
mean-reversion of the spread on the LATER (held-out) data only — every trade is
out of sample by construction.

Lookahead discipline: hedge ratio β and the spread mean/std come from train; the
z-score on test uses those frozen train statistics. Hyperparameters (z entry/exit)
are FIXED classic values, not tuned, so they can't be overfit.

Each completed spread trade pays a 2-leg round trip (round_trips=2). Trades pooled
across pairs are judged by ml/edge_eval against zero (market-neutral has no beta
benchmark).

Usage:
    cd apps/api && PYTHONPATH=. .venv/bin/python scripts/statarb_experiment.py
"""

from __future__ import annotations

import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets import get_market_adapter
from ml import costs, edge_eval

logging.basicConfig(level=logging.WARNING)

TRAIN_FRAC = 0.6
Z_ENTRY = 1.0     # fixed classic thresholds (not tuned → not overfit)
Z_EXIT = 0.0
Z_STOP = 3.0      # divergence stop — without it, non-reverting losers never close
START = "2015-01-01"   # max equity history → enough held-out trades for the gate

EQUITY_PAIRS = [
    ("KO", "PEP"), ("V", "MA"), ("HD", "LOW"), ("XOM", "CVX"), ("JPM", "BAC"),
    ("GOOGL", "META"), ("MSFT", "AAPL"), ("PEP", "MDLZ"), ("WMT", "TGT"),
    ("COST", "WMT"), ("PG", "CL"), ("PEP", "KO"), ("UPS", "FDX"), ("MCD", "YUM"),
    ("LOW", "HD"), ("ADBE", "CRM"), ("AMD", "NVDA"), ("INTC", "AMD"),
    ("BAC", "WFC"), ("GS", "MS"), ("C", "BAC"), ("CVX", "COP"), ("UNH", "CVS"),
    ("LIN", "APD"), ("CAT", "DE"), ("DUK", "SO"), ("T", "VZ"), ("AXP", "MA"),
]
CRYPTO_PAIRS = [("ETH-USD", "BTC-USD"), ("SOL-USD", "ETH-USD"), ("LTC-USD", "BTC-USD")]


def _closes(adapter, sym, timeframe, asset_class):
    if asset_class == "equity":
        from markets.equity_data import fetch_equity_ohlcv
        df = fetch_equity_ohlcv(sym, timeframe, start=START)
    else:
        df = adapter.fetch_ohlcv(sym, timeframe)
    return df["close"].astype(float) if df is not None and len(df) > 200 else None


def pair_trades(a: pd.Series, b: pd.Series, asset_class: str):
    """Held-out spread-reversion trades for one pair: list of realized returns + entry ts."""
    j = pd.concat([np.log(a), np.log(b)], axis=1, keys=["a", "b"]).dropna()
    if len(j) < 250:
        return []
    cut = int(len(j) * TRAIN_FRAC)
    la, lb = j["a"].to_numpy(), j["b"].to_numpy()
    # hedge ratio on TRAIN log-prices (OLS through the data, with intercept)
    A = np.vstack([lb[:cut], np.ones(cut)]).T
    beta, alpha = np.linalg.lstsq(A, la[:cut], rcond=None)[0]
    spread = la - (beta * lb + alpha)
    mu, sd = spread[:cut].mean(), spread[:cut].std()
    if sd <= 0:
        return []
    z = (spread - mu) / sd

    dla = np.diff(la); dlb = np.diff(lb)
    sr = dla - beta * dlb                 # per-bar spread return (dollar-neutral legs)
    idx = j.index

    trades, pos, entry_i, cum = [], 0, None, 0.0
    last = len(j) - 1
    for t in range(cut, last):             # trade test region only
        if pos == 0:
            if z[t] > Z_ENTRY:
                pos, entry_i, cum = -1, t, 0.0     # spread rich → short spread
            elif z[t] < -Z_ENTRY:
                pos, entry_i, cum = 1, t, 0.0      # spread cheap → long spread
        else:
            cum += pos * sr[t]                     # accrue next-bar spread return
            reverted = (pos == 1 and z[t] >= Z_EXIT) or (pos == -1 and z[t] <= Z_EXIT)
            stopped = abs(z[t]) > Z_STOP           # diverged further → cut the loss
            if reverted or stopped:
                trades.append((idx[entry_i].value, cum))
                pos = 0
    if pos != 0:                            # force-close at end — book the open trade honestly
        trades.append((idx[entry_i].value, cum))
    return trades


def run(asset_class, pairs, timeframe):
    adapter = get_market_adapter(asset_class)
    closes = {}
    syms = {s for p in pairs for s in p}
    for s in syms:
        try:
            c = _closes(adapter, s, timeframe, asset_class)
            if c is not None:
                closes[s] = c
        except Exception as exc:
            print(f"  skip {s}: {exc}")

    all_rets, n_pairs = [], 0
    for a_sym, b_sym in pairs:
        if a_sym not in closes or b_sym not in closes:
            continue
        a, b = closes[a_sym].align(closes[b_sym], join="inner")
        tr = pair_trades(a, b, asset_class)
        if tr:
            n_pairs += 1
            all_rets.extend(tr)
    if not all_rets:
        print(f"{asset_class}: no trades"); return

    rets = np.array([r for _, r in all_rets])
    cf = costs.cost_frac(asset_class)
    stats = edge_eval.trade_stats(rets, cost_frac=cf, round_trips=2)  # 2 legs
    print(f"\n=== stat-arb {asset_class} ({timeframe}): {n_pairs} pairs, "
          f"{len(rets)} held-out trades, 2-leg cost {2*cf*1e4:.0f}bps ===")
    print(edge_eval.format_row("spread-reversion", stats))
    print(edge_eval.verdict(f"stat-arb {asset_class}", stats))


def main():
    run("equity", EQUITY_PAIRS, "daily")
    run("crypto", CRYPTO_PAIRS, "daily")


if __name__ == "__main__":
    main()
