#!/usr/bin/env python
"""Can the strategies be COMBINED into a positive-edge blend? (offline, OOS)

The per-strategy edge sweep (strategy_edge_experiment.py) showed the equal-weight
blend destroys value — it averages winners with losers. This asks the decisive
follow-up: does *edge-weighting* the blend — weights fit on past data, judged on
future data — produce a net-positive blend? If yes, the weights ship through the
existing `load_learned_weights` path (build_default_combiner already consumes
`strategy_weights_{asset}.json`). If no, the strategy set is unsalvageable by
reweighting and the honest move is new strategies, not more tuning.

Protocol (per asset class, faithful to the live combiner):
  1. Compute each strategy's continuous signal strength per bar over the
     trailing window the live tick passes.
  2. Chronological split: weights are fit on the EARLIER `--train-frac`, every
     metric is reported on the LATER hold-out only.
  3. Fit weights = max(0, net-mean-per-bar) on train, normalized → sub-cost
     strategies get zero (dropped). Blend strength = Σ wᵢ·strengthᵢ, thresholded
     to a position exactly like combine_to_result.
  4. Compare on the hold-out: edge-weighted blend vs equal-weight blend vs the
     single best train strategy vs buy & hold.
  5. Write the weights JSON only if the edge blend is net-positive AND beats
     equal-weight out of sample. `--write` required to persist.

Usage:
    cd apps/api
    PYTHONPATH=. .venv/bin/python scripts/strategy_weight_fit.py
    PYTHONPATH=. .venv/bin/python scripts/strategy_weight_fit.py --asset-class forex --write
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from markets import get_market_adapter
from ml import costs
from ml.sequences import FeatureEngineer
from ml.strategies.combiner import _STRATEGY_FACTORIES

logging.basicConfig(level=logging.WARNING)

THRESHOLD = 0.1
LOOKBACK = 160
CRYPTO_DAYS = 90

_UNIVERSE = {
    "equity": (["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "WMT"], "daily", 252),
    "crypto": (["BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", "AVAX-USD"], "5m", 365 * 24 * 12),
    "forex": (["EUR_USD", "GBP_USD", "AUD_USD", "USD_JPY", "USD_CAD"], "4h", 6 * 252),
}
STRATS = [n for n in _STRATEGY_FACTORIES if n != "ml"]


def _deep_crypto(adapter, symbol, days):
    product = adapter.normalize_symbol(symbol)
    end = adapter._now()
    rows = adapter._fetch_paginated(product, end - timedelta(days=days), end, 300)
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    df = df.drop_duplicates(subset="ts").sort_values("ts").set_index("ts").astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def _strength_matrix(fe: pd.DataFrame, warmup: int):
    """(strengths[bars-1, n_strat], next_ret[bars-1]) for one symbol.

    Each strategy's continuous strength per bar on the trailing window — the
    raw input the combiner weights, before thresholding."""
    strategies = [_STRATEGY_FACTORIES[n]() for n in STRATS]
    close = fe["c"].to_numpy(dtype=float)
    n = len(fe)
    S = np.zeros((n, len(strategies)))
    for t in range(warmup, n):
        window = fe.iloc[max(0, t - LOOKBACK):t + 1]
        px = float(close[t])
        for j, strat in enumerate(strategies):
            try:
                S[t, j] = float(strat.generate_signal("SYM", window, px).strength)
            except Exception:
                S[t, j] = 0.0
    next_ret = np.zeros(n)
    next_ret[:-1] = close[1:] / np.where(close[:-1] != 0, close[:-1], 1.0) - 1.0
    return S[:-1], next_ret[:-1]


def _net_series(strength_col, ret, asset_class):
    """Net per-bar return of trading one strength column (threshold → hold → cost)."""
    pos = np.where(strength_col > THRESHOLD, 1.0, np.where(strength_col < -THRESHOLD, -1.0, 0.0))
    gross = pos * ret
    flips = np.abs(np.diff(np.concatenate([[0.0], pos]))) > 1e-9
    return gross - flips * costs.cost_frac(asset_class)


def _stats(net, ppy):
    return {
        "net_bps": float(net.mean() * 1e4),
        "sharpe": costs.sharpe(net, ppy) or 0.0,
        "total_pct": float(net.sum() * 100.0),
    }


def run(asset_class: str, train_frac: float, write: bool) -> None:
    symbols, timeframe, ppy = _UNIVERSE[asset_class]
    adapter = get_market_adapter(asset_class)
    fe_engine = FeatureEngineer()

    S_parts, r_parts = [], []
    for s in symbols:
        try:
            df = _deep_crypto(adapter, s, CRYPTO_DAYS) if asset_class == "crypto" \
                else adapter.fetch_ohlcv(s, timeframe)
            fe = fe_engine.compute(df)
            if len(fe) <= LOOKBACK + 80:
                continue
            S, r = _strength_matrix(fe, 50)
            # chronological split inside each symbol, then pool
            cut = int(len(S) * train_frac)
            S_parts.append((S[:cut], S[cut:]))
            r_parts.append((r[:cut], r[cut:]))
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    if not S_parts:
        print(f"{asset_class}: no data")
        return

    S_tr = np.vstack([a for a, _ in S_parts]); r_tr = np.concatenate([a for a, _ in r_parts])
    S_te = np.vstack([b for _, b in S_parts]); r_te = np.concatenate([b for _, b in r_parts])

    # Fit weights on train: per-strategy net mean per-bar return, floored at 0.
    edges = np.array([_net_series(S_tr[:, j], r_tr, asset_class).mean() for j in range(len(STRATS))])
    w = np.clip(edges, 0.0, None)
    survivors = {STRATS[j]: float(w[j]) for j in range(len(STRATS)) if w[j] > 0}

    print(f"\n=== {asset_class} ({timeframe}) train={len(r_tr)} test={len(r_te)} bars "
          f"cost={costs.cost_bps(asset_class):.0f}bps ===")
    if w.sum() <= 0:
        print("  NO strategy has positive net edge on train → blend unsalvageable by reweighting.")
        return
    wn = w / w.sum()
    print("  fitted weights (train edge):  " +
          ", ".join(f"{STRATS[j]} {wn[j]:.2f}" for j in range(len(STRATS)) if wn[j] > 0))

    # Out-of-sample comparison on the held-out tail.
    eq_strength = S_te.mean(axis=1)
    edge_strength = S_te @ wn
    best_j = int(np.argmax(edges))
    rows = {
        "buy_hold":   _stats(r_te, ppy),  # always-long reference
        "equal_blend": _stats(_net_series(eq_strength, r_te, asset_class), ppy),
        "edge_blend":  _stats(_net_series(edge_strength, r_te, asset_class), ppy),
        f"best_single({STRATS[best_j]})": _stats(_net_series(S_te[:, best_j], r_te, asset_class), ppy),
    }
    print(f"  {'config':<26}{'net_bps':>9}{'sharpe':>9}{'total%':>9}   (HOLD-OUT)")
    for name, m in rows.items():
        print(f"  {name:<26}{m['net_bps']:>9.3f}{m['sharpe']:>9.2f}{m['total_pct']:>9.2f}")

    edge_sh = rows["edge_blend"]["sharpe"]
    eq_sh = rows["equal_blend"]["sharpe"]
    verdict_ok = edge_sh > 0 and edge_sh > eq_sh
    print(f"  VERDICT: edge-weighting {'BEATS' if verdict_ok else 'does NOT beat'} "
          f"equal-weight out of sample (edge {edge_sh:.2f} vs equal {eq_sh:.2f}).")

    if write and verdict_ok:
        path = Path(settings.model_dir) / f"strategy_weights_{asset_class}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Refit on ALL data for the shipped weights (the split was only to
        # validate that edge-weighting generalizes; ship uses every bar).
        S_all = np.vstack([S_tr, S_te])
        r_all = np.concatenate([r_tr, r_te])
        full_edges = np.array([_net_series(S_all[:, j], r_all, asset_class).mean()
                               for j in range(len(STRATS))])
        fw = np.clip(full_edges, 0.0, None)
        fw = fw / fw.sum()
        out = {STRATS[j]: round(float(fw[j]), 6) for j in range(len(STRATS)) if fw[j] > 0}
        path.write_text(json.dumps(out, indent=2, sort_keys=True))
        print(f"  WROTE {path} → {out}")
    elif write:
        print("  --write given but verdict failed → no file written (won't ship a losing blend).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset-class", action="append", dest="acs")
    ap.add_argument("--train-frac", type=float, default=0.6)
    ap.add_argument("--write", action="store_true", help="persist weights if OOS verdict passes")
    args = ap.parse_args()
    for ac in (args.acs or ["equity", "forex", "crypto"]):
        try:
            run(ac, args.train_frac, args.write)
        except Exception as exc:
            print(f"{ac}: FAILED — {exc}")


if __name__ == "__main__":
    main()
