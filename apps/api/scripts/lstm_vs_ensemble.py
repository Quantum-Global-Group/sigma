#!/usr/bin/env python
"""Measured comparison: per-asset LSTM vs ensemble on a walk-forward (chronological,
per-symbol) out-of-sample split. Trains nothing to disk; reports OOS 3-class and
directional accuracy so we only adopt LSTM where it actually beats the ensemble.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/lstm_vs_ensemble.py
"""
from __future__ import annotations
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from sklearn.metrics import accuracy_score
from sklearn.utils.class_weight import compute_sample_weight, compute_class_weight

from markets import get_market_adapter
from ml.features import build_features
from ml.models.base import label_signals
from ml.models.ensemble import EnsembleSignalModel
from ml.models.lstm import SEQ_LEN, LSTMModel

DEFAULTS = {
    "equity": (["AAPL","MSFT","GOOG","AMZN","META","NVDA","TSLA","JPM","V","WMT"], "daily", 0.005),
    "forex":  (["EUR_USD","GBP_USD","AUD_USD","USD_JPY","USD_CAD"], "4h", 0.001),
    "crypto": (["BTC-USD","ETH-USD","SOL-USD","LINK-USD","AVAX-USD"], "5m", 0.002),
}
EPOCHS = 15


def _dir_acc(pred, y):
    m = pred != 1
    if m.sum() == 0:
        return None, 0
    tot = (y[m] != 1).sum()
    ok = ((pred[m] == y[m]) & (y[m] != 1)).sum()
    return (ok / tot if tot else None), int(m.sum())


def _seqs(X, y, k):
    """Sliding windows; split by end-index (chronological): end < k -> train."""
    n = len(X)
    if n <= SEQ_LEN:
        return None
    s = np.stack([X[i - SEQ_LEN + 1:i + 1] for i in range(SEQ_LEN - 1, n)])
    sy = y[SEQ_LEN - 1:]
    ends = np.arange(SEQ_LEN - 1, n)
    tr = ends < k
    return s[tr], sy[tr], s[~tr], sy[~tr]


def run_asset(asset, symbols, tf, thr):
    adapter = get_market_adapter(asset)
    Xtr, ytr, Xv, yv = [], [], [], []
    sXtr, sytr, sXv, syv = [], [], [], []
    for sym in symbols:
        try:
            df = adapter.fetch_ohlcv(sym, tf)
        except Exception:
            continue
        feat = build_features(df).dropna()
        fr = df["close"].pct_change().shift(-1).reindex(feat.index).fillna(0.0)
        y = np.asarray(label_signals(fr, threshold=thr))
        feat = feat.iloc[:-1]; y = y[:-1]
        if len(feat) < SEQ_LEN + 30:
            continue
        k = int(len(feat) * 0.8)
        Xtr.append(feat.iloc[:k]); ytr.append(y[:k]); Xv.append(feat.iloc[k:]); yv.append(y[k:])
        sq = _seqs(feat.values, y, k)
        if sq:
            sXtr.append(sq[0]); sytr.append(sq[1]); sXv.append(sq[2]); syv.append(sq[3])

    import pandas as pd
    Xtr_, ytr_ = pd.concat(Xtr), np.concatenate(ytr)
    Xv_, yv_ = pd.concat(Xv), np.concatenate(yv)

    # ensemble
    ens = EnsembleSignalModel(); ens.feature_names = list(Xtr_.columns)
    sw = compute_sample_weight("balanced", ytr_)
    ens.rf.fit(Xtr_.values, ytr_, sample_weight=sw); ens.xgb.fit(Xtr_.values, ytr_, sample_weight=sw)
    ep = np.argmax((ens.rf.predict_proba(Xv_.values) + ens.xgb.predict_proba(Xv_.values)) / 2, axis=1)
    e3 = accuracy_score(yv_, ep); ed, en = _dir_acc(ep, yv_)

    # lstm (class-weighted CE) on chronological sequences
    import torch, torch.nn as nn
    Xs, ys = np.concatenate(sXtr), np.concatenate(sytr)
    Xvs, yvs = np.concatenate(sXv), np.concatenate(syv)
    net = LSTMModel.build(Xs.shape[2])
    classes = np.unique(ys)
    cw = compute_class_weight("balanced", classes=classes, y=ys)
    wvec = np.ones(3);
    for c, w in zip(classes, cw): wvec[int(c)] = w
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(wvec, dtype=torch.float32))
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    Xt = torch.tensor(Xs, dtype=torch.float32); yt = torch.tensor(ys, dtype=torch.long)
    net.train()
    for _ in range(EPOCHS):
        perm = torch.randperm(len(Xt))
        for i in range(0, len(Xt), 64):
            idx = perm[i:i+64]
            opt.zero_grad(); loss = loss_fn(net(Xt[idx]), yt[idx]); loss.backward(); opt.step()
    net.eval()
    with torch.no_grad():
        lp = torch.argmax(net(torch.tensor(Xvs, dtype=torch.float32)), dim=-1).numpy()
    l3 = accuracy_score(yvs, lp); ld, ln = _dir_acc(lp, yvs)
    return (e3, ed, en), (l3, ld, ln)


for asset, (syms, tf, thr) in DEFAULTS.items():
    (e3, ed, en), (l3, ld, ln) = run_asset(asset, syms, tf, thr)
    fed = f"{ed:.3f}" if ed is not None else "n/a"; fld = f"{ld:.3f}" if ld is not None else "n/a"
    print(f"{asset:6} ENSEMBLE oos_acc={e3:.3f} dir_acc={fed} (n~{en})  |  "
          f"LSTM oos_acc={l3:.3f} dir_acc={fld} (n~{ln})")
