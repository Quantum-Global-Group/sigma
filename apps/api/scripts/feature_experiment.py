#!/usr/bin/env python
"""Measured feature round — compare candidate features against the current set on
a walk-forward (chronological, per-symbol) out-of-sample split. Trains nothing to
disk; just reports OOS metrics so we only adopt features that actually help.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/feature_experiment.py
"""
from __future__ import annotations
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.utils.class_weight import compute_sample_weight

from markets import get_market_adapter
from ml.features import build_features
from ml.models.base import label_signals
from ml.models.ensemble import EnsembleSignalModel

DEFAULTS = {
    "equity": (["AAPL","MSFT","GOOG","AMZN","META","NVDA","TSLA","JPM","V","WMT"], "daily", 0.005),
    "forex":  (["EUR_USD","GBP_USD","AUD_USD","USD_JPY","USD_CAD"], "4h", 0.001),
    "crypto": (["BTC-USD","ETH-USD","SOL-USD","LINK-USD","AVAX-USD"], "5m", 0.002),
}


def candidate_features(df: pd.DataFrame) -> pd.DataFrame:
    """New features under test: multi-timeframe trend, vol regime, volume micro."""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    out = pd.DataFrame(index=df.index)
    ema50, ema100 = close.ewm(span=50).mean(), close.ewm(span=100).mean()
    out["ema_ratio_long"] = ema50 / (ema100 + 1e-12)                       # longer trend
    out["mom_accel"] = close.pct_change(10) - close.pct_change(10).shift(10)  # momentum accel
    obv = (np.sign(close.diff()).fillna(0.0) * vol).cumsum()
    out["obv_slope"] = obv.diff(10) / (obv.rolling(20).mean().abs() + 1e-9)   # volume micro
    out["vol_of_vol"] = close.pct_change().rolling(10).std().rolling(20).std()  # vol regime
    rhi, rlo = close.rolling(20).max(), close.rolling(20).min()
    out["range_pos"] = (close - rlo) / ((rhi - rlo) + 1e-9)                # position in range
    return out


def _metrics(model, X_val, y_val):
    proba = (model.rf.predict_proba(X_val.values) + model.xgb.predict_proba(X_val.values)) / 2.0
    pred = np.argmax(proba, axis=1)
    acc3 = accuracy_score(y_val, pred)
    # Directional accuracy: among non-HOLD predictions, fraction matching a non-HOLD truth direction
    mask = pred != 1
    if mask.sum() == 0:
        return acc3, None, 0
    dir_ok = ((pred[mask] == y_val[mask]) & (y_val[mask] != 1)).sum()
    dir_tot = (y_val[mask] != 1).sum()
    return acc3, (dir_ok / dir_tot if dir_tot else None), int(mask.sum())


def run(asset, symbols, timeframe, threshold, augment):
    adapter = get_market_adapter(asset)
    Xtr, ytr, Xv, yv = [], [], [], []
    for sym in symbols:
        try:
            df = adapter.fetch_ohlcv(sym, timeframe)
        except Exception:
            continue
        base = build_features(df)
        feats = base.join(candidate_features(df)) if augment else base
        feats = feats.dropna()
        fr = df["close"].pct_change().shift(-1).reindex(feats.index).fillna(0.0)
        y = label_signals(fr, threshold=threshold)[:-1]
        feats = feats.iloc[:-1]
        if len(feats) < 50:
            continue
        k = int(len(feats) * 0.8)                  # chronological per-symbol split
        Xtr.append(feats.iloc[:k]); ytr.append(y[:k])
        Xv.append(feats.iloc[k:]); yv.append(y[k:])
    X_tr, y_tr = pd.concat(Xtr), np.concatenate(ytr)
    X_val, y_val = pd.concat(Xv), np.concatenate(yv)
    m = EnsembleSignalModel()
    m.feature_names = list(X_tr.columns)
    sw = compute_sample_weight("balanced", y_tr)
    m.rf.fit(X_tr.values, y_tr, sample_weight=sw)
    m.xgb.fit(X_tr.values, y_tr, sample_weight=sw)
    return _metrics(m, X_val, y_val), X_tr.shape[1]


for asset, (syms, tf, thr) in DEFAULTS.items():
    (b3, bdir, bn), bf = run(asset, syms, tf, thr, augment=False)
    (a3, adir, an), af = run(asset, syms, tf, thr, augment=True)
    bd = f"{bdir:.3f}" if bdir is not None else "n/a"
    ad = f"{adir:.3f}" if adir is not None else "n/a"
    print(f"{asset:6} BASE(f={bf}): oos_acc={b3:.3f} dir_acc={bd} (n_dir~{bn})  |  "
          f"AUG(f={af}): oos_acc={a3:.3f} dir_acc={ad} (n_dir~{an})")
