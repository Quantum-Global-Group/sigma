#!/usr/bin/env python
"""Re-validate crypto meta-labeling on PROPER data, out-of-sample, net of cost.

Crypto meta-labeling is the only positive result the alpha program ever produced
— but it was trained on ~1 day of 5m data (the Coinbase adapter caps 5m history
at 24h). This rebuilds it on a real window and asks the only question that
matters: on bars the combiner wants to trade, does gating by the meta-model's
P(win) — trained on the past, judged on the future — turn a net-of-cost LOSER
into a WINNER?

Meta-labeling is a filter, not a signal generator. It can only help if there is
*conditional* edge: the combiner is unconditionally edgeless (measured), but the
meta-model might still flag *which* of its signals are likelier right. High bar,
honest test.

Each "trade" is a triple-barrier hold (pt/sl/vbar), so it pays the 8bps
round-trip once — not per bar. Reported on the HELD-OUT tail only:
  baseline  = take every combiner side
  meta@tau  = take only sides with P(win) > tau
for win rate, net mean return per trade, total net %, and trade Sharpe.

Usage:
    cd apps/api
    PYTHONPATH=. .venv/bin/python scripts/crypto_meta_revalidate.py
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
from ml import costs
from ml.features import build_features
from ml.meta_label import MetaLabeler
from ml.meta_serving import META_DESCRIPTORS
from ml.sequences import FeatureEngineer
from ml.strategies import build_default_combiner
from ml.triple_barrier import meta_bin, side_pnl, triple_barrier

logging.basicConfig(level=logging.WARNING)

SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", "AVAX-USD"]
DAYS = 75
LB = 160
BAND = 0.1          # |strength| for a non-flat side (crypto _META_DEFAULTS)
PT = SL = 1.5
VBAR = 24
TRAIN_FRAC = 0.6
COST = costs.cost_frac("crypto")   # 8 bps round-trip, charged once per trade


def _deep_crypto(adapter, symbol, days):
    product = adapter.normalize_symbol(symbol)
    end = adapter._now()
    rows = adapter._fetch_paginated(product, end - timedelta(days=days), end, 300)
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    df = df.drop_duplicates(subset="ts").sort_values("ts").set_index("ts").astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def build_symbol(adapter, combiner, symbol):
    """Per-symbol taken-bet rows: (X, y_win, signed_ret, is_train)."""
    df = _deep_crypto(adapter, symbol, DAYS)
    fe = FeatureEngineer().compute(df)
    if len(fe) < LB + 100:
        return None
    close = fe["c"].to_numpy(dtype=float)
    atr = fe["atr"].to_numpy(dtype=float)
    target = np.clip(atr / np.where(close > 0, close, 1.0), 1e-4, None)

    strength = np.zeros(len(fe))
    conf = np.zeros(len(fe))
    for t in range(LB, len(fe)):
        try:
            sig = combiner.combine_signals(symbol, fe.iloc[t - LB:t + 1], float(close[t]), min_agreement=0)
            strength[t], conf[t] = sig.strength, sig.confidence
        except Exception:
            pass
    side = np.where(strength > BAND, 1, np.where(strength < -BAND, -1, 0)).astype(int)

    tb = triple_barrier(close, target, pt_mult=PT, sl_mult=SL, vbar_bars=VBAR)
    win = meta_bin(tb["ret"].to_numpy(), side)
    signed = side_pnl(tb["ret"].to_numpy(), side)   # realized signed return per trade

    mf = build_features(df)
    pos = df.index.get_indexer(mf.index)
    ok = pos >= 0
    mfa = mf.to_numpy()[ok]
    posv = pos[ok]
    take = side[posv] != 0
    if take.sum() < 50:
        return None

    descr = np.column_stack([strength[posv], conf[posv], side[posv].astype(float), np.abs(strength[posv])])
    X = pd.DataFrame(np.column_stack([mfa, descr])[take], columns=list(mf.columns) + META_DESCRIPTORS)
    y = win[posv][take]
    ret = signed[posv][take]
    # chronological: earlier TRAIN_FRAC of this symbol's taken bets = train
    cut = int(len(X) * TRAIN_FRAC)
    is_train = np.zeros(len(X), dtype=bool); is_train[:cut] = True
    return X, y, ret, is_train


def _econ(ret, label):
    """Net-of-cost trade economics for a set of taken trades."""
    if len(ret) == 0:
        return f"  {label:<16} 0 trades"
    net = ret - COST
    sh = costs.sharpe(net) or 0.0
    return (f"  {label:<16}{len(ret):>7} trades  win {np.mean(ret > 0)*100:>5.1f}%  "
            f"gross {np.mean(ret)*1e4:>7.1f}bps  net {np.mean(net)*1e4:>7.1f}bps  "
            f"total {np.sum(net)*100:>7.2f}%  sharpe {sh:>6.2f}")


def main():
    adapter = get_market_adapter("crypto")
    combiner = build_default_combiner("crypto")
    parts = []
    for s in SYMBOLS:
        try:
            r = build_symbol(adapter, combiner, s)
            if r is not None:
                parts.append(r)
                print(f"  {s}: {len(r[0])} taken bets")
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    if not parts:
        print("no data"); return

    X = pd.concat([p[0] for p in parts], ignore_index=True)
    y = np.concatenate([p[1] for p in parts])
    ret = np.concatenate([p[2] for p in parts])
    tr = np.concatenate([p[3] for p in parts])

    print(f"\n=== crypto meta re-validation: {DAYS}d 5m, {len(X)} taken bets "
          f"({tr.sum()} train / {(~tr).sum()} test), cost {COST*1e4:.0f}bps/trade ===")
    print(f"  base win rate (all, full): {np.mean(y)*100:.1f}%")

    meta = MetaLabeler().train(X[tr], y[tr])
    p_test = meta.predict_proba_win(X[~tr])
    ret_test = ret[~tr]

    print("\n  HELD-OUT economics:")
    print(_econ(ret_test, "baseline(all)"))
    for tau in (0.50, 0.55, 0.60, 0.65):
        keep = p_test > tau
        print(_econ(ret_test[keep], f"meta>{tau:.2f}"))

    base_net = np.mean(ret_test - COST)
    best = None
    for tau in (0.50, 0.55, 0.60, 0.65):
        keep = p_test > tau
        if keep.sum() >= 30:
            net = np.mean(ret_test[keep] - COST)
            if best is None or net > best[1]:
                best = (tau, net)
    print()
    if best and best[1] > 0 and best[1] > base_net:
        print(f"  VERDICT: meta gating @tau={best[0]:.2f} is net-POSITIVE ({best[1]*1e4:.1f}bps/trade) "
              f"and beats baseline ({base_net*1e4:.1f}bps) out of sample — worth pursuing.")
    else:
        print(f"  VERDICT: no tau makes the combiner's signals net-positive out of sample "
              f"(baseline {base_net*1e4:.1f}bps/trade). Crypto meta-labeling does not survive "
              f"proper data — the 1-day 'win' was noise.")


if __name__ == "__main__":
    main()
