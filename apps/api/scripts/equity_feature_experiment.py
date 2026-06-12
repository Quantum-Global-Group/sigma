#!/usr/bin/env python
"""Purged-CV equity feature/model experiments — find a config that beats the gate.

The train gate refused the equity ensemble (val_acc 0.348 < majority 0.377,
train_acc 0.90 → pure overfit). This harness measures candidate fixes the
honest way — purged k-fold CV (ml/cv.py) across pooled tickers — so iteration
happens against CV folds and the gate's chronological holdout stays unburned
for the single final check in train_models.py.

Variants (cumulative):
  V0  legacy raw-dollar ATR, 730d history, default tree params   (the refused config)
  V1  atr_pct (scale-free),  730d,        default
  V2  atr_pct,               long history (--start), default
  V3  atr_pct,               long,        regularized trees
  V4  V3 + wide 30-name universe

Reported per variant: mean±std fold accuracy, mean majority baseline, the
edge (acc − baseline, the gate's criterion), and rank-IC of the directional
score vs realized next-bar returns.

Usage:
    PYTHONPATH=. python scripts/equity_feature_experiment.py
    PYTHONPATH=. python scripts/equity_feature_experiment.py --start 2016-01-01 --splits 5
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets.equity_data import fetch_equity_ohlcv
from ml.cv import purged_kfold_splits
from ml.features import build_features
from ml.models.base import label_signals
from ml.train_gate import rank_ic

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("equity_experiment")

CORE_10 = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "WMT"]
WIDE_30 = CORE_10 + [
    "UNH", "XOM", "PG", "HD", "MA", "COST", "KO", "PEP", "BAC", "ADBE",
    "CRM", "NFLX", "AMD", "INTC", "DIS", "CSCO", "MRK", "PFE", "T", "CAT",
]

DEFAULT_PARAMS = dict(rf_depth=8, rf_leaf=5, rf_n=200, xgb_depth=6, xgb_lr=0.05,
                      xgb_n=200, xgb_mcw=1, xgb_lambda=1.0)
REGULARIZED_PARAMS = dict(rf_depth=4, rf_leaf=100, rf_n=300, xgb_depth=3, xgb_lr=0.05,
                          xgb_n=200, xgb_mcw=50, xgb_lambda=5.0)


def fetch_universe(symbols: list[str], start: str | None) -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        try:
            df = fetch_equity_ohlcv(s, "daily", start=start)
            if df is not None and len(df) > 120:
                out[s] = df
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    return out


def build_dataset(dfs: dict[str, pd.DataFrame], *, legacy_atr: bool, threshold: float = 0.005):
    """Pooled (X, y, future_returns, t_start, t_end) across tickers.

    Timestamps ride along so purged CV can drop any train row whose label
    window overlaps a test fold — across all tickers at once."""
    Xp, yp, rp, tsp, tep = [], [], [], [], []
    for sym, df in dfs.items():
        feats = build_features(df)
        if feats.empty:
            continue
        if legacy_atr:
            # Reconstruct the refused config's raw-dollar ATR for the A/B.
            close = df["close"].reindex(feats.index)
            feats = feats.assign(atr_14=feats["atr_pct"] * close).drop(columns=["atr_pct"])
        fut = df["close"].pct_change().shift(-1).reindex(feats.index).fillna(0.0)
        labels = label_signals(fut, threshold=threshold)

        feats, labels = feats.iloc[:-1], labels[:-1]
        rets = fut.to_numpy(dtype=float)[:-1]
        # Epoch-ns floats: tz-aware indexes otherwise pool as object-dtype
        # Timestamp arrays that ml.cv can't coerce. Label realizes one bar
        # ahead, so each row's end-time is the next bar's timestamp.
        ts_ns = pd.DatetimeIndex(feats.index).asi8.astype(float)
        end_pos = np.minimum(np.arange(len(ts_ns)) + 1, len(ts_ns) - 1)
        te_ns = ts_ns[end_pos]

        Xp.append(feats)
        yp.append(labels)
        rp.append(rets)
        tsp.append(ts_ns)
        tep.append(te_ns)

    X = pd.concat(Xp, ignore_index=True)
    return (X, np.concatenate(yp), np.concatenate(rp),
            np.concatenate(tsp), np.concatenate(tep))


def _fit_soft_vote(X_tr, y_tr, p):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.utils.class_weight import compute_sample_weight
    from xgboost import XGBClassifier

    rf = RandomForestClassifier(n_estimators=p["rf_n"], max_depth=p["rf_depth"],
                                min_samples_leaf=p["rf_leaf"], n_jobs=-1, random_state=42)
    xgb = XGBClassifier(n_estimators=p["xgb_n"], max_depth=p["xgb_depth"],
                        learning_rate=p["xgb_lr"], min_child_weight=p["xgb_mcw"],
                        reg_lambda=p["xgb_lambda"], subsample=0.8, colsample_bytree=0.8,
                        objective="multi:softprob", num_class=3, random_state=42, verbosity=0)
    w = compute_sample_weight(class_weight="balanced", y=y_tr)
    rf.fit(X_tr, y_tr, sample_weight=w)
    xgb.fit(X_tr, y_tr, sample_weight=w)
    return rf, xgb


def evaluate(X, y, rets, ts, te, params, *, n_splits: int, embargo: float):
    accs, bases, ics, train_accs = [], [], [], []
    for train_idx, test_idx in purged_kfold_splits(ts, te, n_splits=n_splits, embargo_frac=embargo):
        if len(train_idx) < 500 or len(test_idx) < 100:
            continue
        rf, xgb = _fit_soft_vote(X.values[train_idx], y[train_idx], params)
        proba = (rf.predict_proba(X.values[test_idx]) + xgb.predict_proba(X.values[test_idx])) / 2.0
        pred = np.argmax(proba, axis=1)
        accs.append(float((pred == y[test_idx]).mean()))
        _, counts = np.unique(y[test_idx], return_counts=True)
        bases.append(float(counts.max() / len(test_idx)))
        ic = rank_ic(proba[:, 2] - proba[:, 0], rets[test_idx])
        ics.append(ic if ic is not None else 0.0)
        tr_proba = (rf.predict_proba(X.values[train_idx]) + xgb.predict_proba(X.values[train_idx])) / 2.0
        train_accs.append(float((np.argmax(tr_proba, axis=1) == y[train_idx]).mean()))
    return accs, bases, ics, train_accs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01", help="long-history start for V2+")
    ap.add_argument("--splits", type=int, default=5)
    ap.add_argument("--embargo", type=float, default=0.01)
    ap.add_argument("--threshold", type=float, default=0.005)
    args = ap.parse_args()

    print("fetching 730d core universe …")
    core_short = fetch_universe(CORE_10, None)
    print(f"  {len(core_short)} symbols")
    print(f"fetching {args.start}+ core universe …")
    core_long = fetch_universe(CORE_10, args.start)
    print(f"  {len(core_long)} symbols")
    print(f"fetching {args.start}+ wide universe …")
    wide_long = fetch_universe(WIDE_30, args.start)
    print(f"  {len(wide_long)} symbols")

    variants = [
        ("V0 legacy-atr 730d default", core_short, True, DEFAULT_PARAMS),
        ("V1 atr_pct    730d default", core_short, False, DEFAULT_PARAMS),
        ("V2 atr_pct    long default", core_long, False, DEFAULT_PARAMS),
        ("V3 atr_pct    long regular", core_long, False, REGULARIZED_PARAMS),
        ("V4 V3 + wide-30 universe  ", wide_long, False, REGULARIZED_PARAMS),
    ]

    print(f"\n{'variant':<30} {'n':>6} {'acc':>13} {'base':>6} {'edge':>7} "
          f"{'rank_ic':>15} {'train_acc':>9}")
    for name, dfs, legacy, params in variants:
        X, y, rets, ts, te = build_dataset(dfs, legacy_atr=legacy, threshold=args.threshold)
        accs, bases, ics, tr = evaluate(X, y, rets, ts, te, params,
                                        n_splits=args.splits, embargo=args.embargo)
        if not accs:
            print(f"{name:<30} —  not enough data")
            continue
        edge = np.mean(accs) - np.mean(bases)
        print(f"{name:<30} {len(X):>6} {np.mean(accs):.4f}±{np.std(accs):.3f} "
              f"{np.mean(bases):.4f} {edge:+.4f} {np.mean(ics):+.4f}±{np.std(ics):.3f} "
              f"{np.mean(tr):>9.4f}")


if __name__ == "__main__":
    main()
