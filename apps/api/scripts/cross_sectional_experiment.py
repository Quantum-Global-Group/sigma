#!/usr/bin/env python
"""Measured round — cross-sectional ranking for equities (item #2).

Reframes equity from "will AAPL rise?" (~0.52, hard) to "will AAPL OUTPERFORM the
universe today?" (more learnable, market-neutral, many simultaneous bets). Builds a
date×symbol panel over a broad universe, cross-sectionally normalizes features per
date, targets relative outperformance (next-day return above the cross-sectional
median), trains a gradient-boosted classifier, and evaluates on a purged-by-date
walk-forward split.

Reports (net-of-cost):
  rank IC   — mean per-date Spearman(pred_score, next_return) across names.
  L/S       — long top-quantile / short bottom-quantile daily spread → Sharpe, mean.
  turnover  — avg fraction of the long basket that changes day-to-day.
Adopt iff rank IC is positive/stable AND the net L/S Sharpe beats the per-symbol
baseline (equity directional Sharpe ≈ 0 in prior rounds).

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/cross_sectional_experiment.py
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.utils.class_weight import compute_sample_weight

from markets import get_market_adapter
from ml.costs import cost_frac
from ml.features import build_features

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "JPM", "V", "WMT",
    "JNJ", "PG", "MA", "HD", "BAC", "XOM", "CVX", "KO", "PEP", "COST",
    "MRK", "ABBV", "AVGO", "ADBE", "CRM", "NFLX", "DIS", "CSCO", "INTC", "AMD",
    "QCOM", "TXN", "NKE", "MCD", "UNH", "LLY", "WFC", "GS", "MS", "CAT",
]
TF = "daily"
TEST_FRAC = 0.2
QUANTILE = 0.2          # long top 20% / short bottom 20%
COST = cost_frac("equity")
HORIZONS = [1, 5, 20]   # forward-return horizons (days): daily, weekly, monthly


def build_panel():
    adapter = get_market_adapter("equity")
    parts = []
    for sym in UNIVERSE:
        try:
            df = adapter.fetch_ohlcv(sym, TF)
        except Exception:
            continue
        if df is None or len(df) < 120:
            continue
        f = build_features(df).copy()
        for h in HORIZONS:
            f[f"fwd_{h}"] = (df["close"].shift(-h) / df["close"] - 1.0).reindex(f.index)
        f["sym"] = sym
        f["date"] = f.index
        parts.append(f)
    if not parts:
        raise RuntimeError("no panel data")
    panel = pd.concat(parts, ignore_index=True)
    feat_cols = [c for c in panel.columns
                 if c not in ("sym", "date") and not c.startswith("fwd_")]
    # Cross-sectional z-score per date (removes market level → relative signal).
    g = panel.groupby("date")
    panel[feat_cols] = g[feat_cols].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    panel = panel.dropna(subset=feat_cols)
    return panel, feat_cols


def run(panel, feat_cols, h):
    from xgboost import XGBClassifier
    fwd = f"fwd_{h}"
    sub = panel.dropna(subset=[fwd]).copy()
    g = sub.groupby("date")
    sub["target"] = (g[fwd].transform(lambda x: x > x.median())).astype(int)

    dates = np.array(sorted(sub["date"].unique()))
    ci = int(len(dates) * (1 - TEST_FRAC))
    cut = dates[ci]
    purge_before = dates[max(0, ci - h)]               # embargo h dates at the boundary
    train = sub[sub["date"] < purge_before]
    test = sub[sub["date"] >= cut].copy()

    Xtr, ytr = train[feat_cols].to_numpy(), train["target"].to_numpy()
    sw = compute_sample_weight("balanced", ytr)
    clf = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.03,
                        subsample=0.8, colsample_bytree=0.8, eval_metric="logloss", n_jobs=4)
    clf.fit(Xtr, ytr, sample_weight=sw)
    test["score"] = clf.predict_proba(test[feat_cols].to_numpy())[:, 1]

    ics, spreads, long_sets = [], [], []
    for _, day in test.groupby("date"):
        if len(day) < 10:
            continue
        ic = spearmanr(day["score"], day[fwd]).correlation
        if not np.isnan(ic):
            ics.append(ic)
        k = max(1, int(len(day) * QUANTILE))
        ranked = day.sort_values("score", ascending=False)
        spread = ranked.head(k)[fwd].mean() - ranked.tail(k)[fwd].mean() - 2 * COST
        spreads.append(spread)
        long_sets.append(set(ranked.head(k)["sym"]))

    turnover = np.mean([
        1 - len(long_sets[i] & long_sets[i - 1]) / max(1, len(long_sets[i]))
        for i in range(1, len(long_sets))
    ]) if len(long_sets) > 1 else float("nan")
    spreads = np.array(spreads)
    mean_ic = float(np.mean(ics)) if ics else float("nan")
    ir = float(spreads.mean() / (spreads.std() + 1e-12)) if len(spreads) else float("nan")
    print(f"H={h:2d}d  rank_IC={mean_ic:+.4f}  L/S {h}d-spread mean={spreads.mean():+.5f} "
          f"IR={ir:+.3f}  turnover={turnover:.2f}  (n_dates={len(ics)})")


def main():
    panel, feat_cols = build_panel()
    print(f"universe={panel['sym'].nunique()} dates={panel['date'].nunique()} rows={len(panel)}")
    for h in HORIZONS:
        try:
            run(panel, feat_cols, h)
        except Exception as exc:
            print(f"H={h}: ERROR {type(exc).__name__}: {exc}")
    print("baseline to beat: per-symbol equity directional Sharpe ≈ 0 (rank_IC>0 stable + IR>0)")


if __name__ == "__main__":
    main()
