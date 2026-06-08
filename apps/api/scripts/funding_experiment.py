#!/usr/bin/env python
"""Measured round — crypto perpetual funding rate as a differentiated feed (item #5).

Public news was already priced (measured). Funding rate is a non-price, positioning
signal: it reflects perp long/short crowding (high positive funding ⇒ crowded longs,
often a contrarian headwind). It has real history, so it is backtestable — unlike
order-book imbalance (never recorded) or options flow (OpenD blocked).

Pulls Binance USDT-perp klines + funding-rate history (public, no auth), aligns
funding to bars lookahead-safe (last funding with fundingTime ≤ bar open), and runs a
base-vs-base+funding walk-forward OOS comparison on the established yardstick
(directional + 3-class accuracy, net-of-cost long/short Sharpe). Adopt iff it beats
base — same discipline that rejected the technical-feature, LSTM, and sentiment rounds.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/funding_experiment.py
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import requests
from sklearn.metrics import accuracy_score
from sklearn.utils.class_weight import compute_sample_weight

from ml.costs import cost_frac, sharpe
from ml.features import build_features
from ml.models.base import label_signals
from ml.models.ensemble import EnsembleSignalModel

# OKX public market data (Binance fapi is geo-blocked here, HTTP 451).
OKX = "https://www.okx.com"
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "LINK-USDT-SWAP", "AVAX-USDT-SWAP"]
INTERVAL = "4H"
THR = 0.005
COST = cost_frac("crypto")


def fetch_klines(inst, bar=INTERVAL, pages=3, per=300):
    """OKX candles, paginated to older history via `after` (newest-first per page)."""
    rows, after = [], None
    for _ in range(pages):
        params = {"instId": inst, "bar": bar, "limit": per}
        if after:
            params["after"] = after
        r = requests.get(f"{OKX}/api/v5/market/candles", params=params, timeout=25)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            break
        rows += data
        after = data[-1][0]                          # oldest ts in page → next page older
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close",
                                     "vol", "volccy", "volq", "confirm"])
    for c in ("open", "high", "low", "close", "vol"):
        df[c] = df[c].astype(float)
    df.index = pd.to_datetime(df["ts"].astype("int64"), unit="ms")
    return df.rename(columns={"vol": "volume"})[["open", "high", "low", "close", "volume"]].sort_index()


def fetch_funding(inst, pages=4, per=100):
    """OKX funding-rate history, paginated to older history via `after`."""
    rows, after = [], None
    for _ in range(pages):
        params = {"instId": inst, "limit": per}
        if after:
            params["after"] = after
        r = requests.get(f"{OKX}/api/v5/public/funding-rate-history", params=params, timeout=25)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            break
        rows += data
        after = data[-1]["fundingTime"]
    f = pd.DataFrame(rows)
    if f.empty:
        return f
    f["t"] = pd.to_datetime(f["fundingTime"].astype("int64"), unit="ms")
    f["rate"] = f["fundingRate"].astype(float)
    return f[["t", "rate"]].sort_values("t")


def funding_features(df, funding):
    """Lookahead-safe funding features aligned to bar open times."""
    bars = pd.DataFrame({"t": df.index})
    merged = pd.merge_asof(bars, funding, on="t", direction="backward")  # last rate ≤ bar open
    rate = merged["rate"].fillna(0.0).to_numpy()
    s = pd.Series(rate)
    out = pd.DataFrame(index=df.index)
    out["fund_rate"] = rate
    out["fund_cum3"] = s.rolling(3, min_periods=1).sum().to_numpy()        # ~24h funding
    rm, rs = s.rolling(30, min_periods=5).mean(), s.rolling(30, min_periods=5).std()
    out["fund_z"] = ((s - rm) / rs.replace(0, np.nan)).fillna(0.0).to_numpy()
    return out


def _metrics(model, Xv, yv, fwd):
    proba = (model.rf.predict_proba(Xv.values) + model.xgb.predict_proba(Xv.values)) / 2
    pred = np.argmax(proba, axis=1)
    acc3 = accuracy_score(yv, pred)
    m = pred != 1
    dir_acc = None
    if m.sum():
        tot = (yv[m] != 1).sum()
        dir_acc = ((pred[m] == yv[m]) & (yv[m] != 1)).sum() / tot if tot else None
    # net-of-cost long/short: +fwd on BUY, -fwd on SELL, minus cost on each trade
    side = np.where(pred == 2, 1, np.where(pred == 0, -1, 0))
    traded = side != 0
    pnl = side[traded] * fwd[traded] - COST
    shp = sharpe(pnl, periods_per_year=1) if traded.sum() else None
    return acc3, dir_acc, int(m.sum()), shp


def run(augment):
    Xtr, ytr, Xv, yv, fwdv = [], [], [], [], []
    for sym in SYMBOLS:
        try:
            df = fetch_klines(sym)
            funding = fetch_funding(sym)
        except Exception as exc:
            print(f"  fetch failed {sym}: {exc}")
            continue
        base = build_features(df)
        feats = base.join(funding_features(df, funding)) if augment else base
        feats = feats.dropna()
        fr = (df["close"].pct_change().shift(-1).reindex(feats.index).fillna(0.0)).to_numpy()
        y = label_signals(pd.Series(fr), threshold=THR)
        feats, y, fr = feats.iloc[:-1], y[:-1], fr[:-1]
        if len(feats) < 60:
            continue
        k = int(len(feats) * 0.8)
        Xtr.append(feats.iloc[:k]); ytr.append(y[:k])
        Xv.append(feats.iloc[k:]); yv.append(y[k:]); fwdv.append(fr[k:])
    if not Xtr:
        return None
    Xtr_, ytr_ = pd.concat(Xtr), np.concatenate(ytr)
    Xv_, yv_, fwd_ = pd.concat(Xv), np.concatenate(yv), np.concatenate(fwdv)
    m = EnsembleSignalModel(); m.feature_names = list(Xtr_.columns)
    sw = compute_sample_weight("balanced", ytr_)
    m.rf.fit(Xtr_.values, ytr_, sample_weight=sw); m.xgb.fit(Xtr_.values, ytr_, sample_weight=sw)
    return _metrics(m, Xv_, yv_, fwd_), Xtr_.shape[1]


def main():
    base = run(augment=False)
    aug = run(augment=True)
    if base is None or aug is None:
        print("funding experiment: no data (Binance fapi may be geo-blocked here)")
        return
    (b3, bd, bn, bs), bf = base
    (a3, ad, an, as_), af = aug
    fb = f"{bd:.3f}" if bd is not None else "n/a"
    fa = f"{ad:.3f}" if ad is not None else "n/a"
    sb = f"{bs:.3f}" if bs is not None else "n/a"
    sa = f"{as_:.3f}" if as_ is not None else "n/a"
    print(f"crypto BASE  feats={bf} oos_acc={b3:.3f} dir_acc={fb} net_sharpe={sb} (n~{bn})")
    print(f"crypto +FUND feats={af} oos_acc={a3:.3f} dir_acc={fa} net_sharpe={sa} (n~{an})")
    print("adopt iff +FUND beats BASE on dir_acc AND net_sharpe")


if __name__ == "__main__":
    main()
