#!/usr/bin/env python
"""Measured equity sentiment round: does per-day news sentiment add OOS signal?

Pipeline (per symbol): Alpaca historical news -> FinBERT polarity -> per-day mean
(lookahead-safe: a bar uses only news on/before its date) -> add as a feature ->
walk-forward (chronological) OOS comparison of base vs base+sentiment ensemble.

Bounded to a recent window + a few high-news symbols so it runs in minutes.
Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/sentiment_experiment.py
"""
from __future__ import annotations
import sys, os, warnings, datetime as dt
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import requests
from sklearn.metrics import accuracy_score
from sklearn.utils.class_weight import compute_sample_weight

from config import settings
from markets import get_market_adapter
from ml.features import build_features
from ml.models.base import label_signals
from ml.models.ensemble import EnsembleSignalModel

SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
TF, THR = "daily", 0.005
WINDOW_BARS = 320          # ~15 months of daily bars
HDR = {"APCA-API-KEY-ID": settings.alpaca_api_key, "APCA-API-SECRET-KEY": settings.alpaca_secret}

_clf = None
def _finbert():
    global _clf
    if _clf is None:
        from transformers import pipeline
        _clf = pipeline("sentiment-analysis", model="ProsusAI/finbert", top_k=None, device=-1, truncation=True)
    return _clf

def polarity(texts):
    if not texts:
        return []
    clf = _finbert()
    out = []
    for i in range(0, len(texts), 64):
        for scores in clf(texts[i:i+64], batch_size=64):
            d = {s["label"].lower(): s["score"] for s in scores}
            out.append(float(d.get("positive", 0) - d.get("negative", 0)))
    return out

def fetch_news(symbol, start_iso, end_iso, max_pages=40):
    rows, token = [], None
    for _ in range(max_pages):
        p = f"symbols={symbol}&start={start_iso}&end={end_iso}&limit=50&sort=asc"
        if token:
            p += f"&page_token={token}"
        r = requests.get(f"https://data.alpaca.markets/v1beta1/news?{p}", headers=HDR, timeout=25).json()
        for a in r.get("news", []):
            rows.append((a["created_at"], a.get("headline", "") + ". " + (a.get("summary", "") or "")))
        token = r.get("next_page_token")
        if not token:
            break
    return rows

def _dir_acc(pred, y):
    m = pred != 1
    if m.sum() == 0:
        return None, 0
    tot = (y[m] != 1).sum()
    ok = ((pred[m] == y[m]) & (y[m] != 1)).sum()
    return (ok / tot if tot else None), int(m.sum())

def _oos(Xtr, ytr, Xv, yv):
    m = EnsembleSignalModel(); m.feature_names = list(Xtr.columns)
    sw = compute_sample_weight("balanced", ytr)
    m.rf.fit(Xtr.values, ytr, sample_weight=sw); m.xgb.fit(Xtr.values, ytr, sample_weight=sw)
    pred = np.argmax((m.rf.predict_proba(Xv.values) + m.xgb.predict_proba(Xv.values)) / 2, axis=1)
    return accuracy_score(yv, pred), _dir_acc(pred, yv)

adapter = get_market_adapter("equity")
base_tr_X, base_tr_y, base_v_X, base_v_y = [], [], [], []
aug_tr_X, aug_v_X = [], []
n_news_total = 0

for sym in SYMBOLS:
    df = adapter.fetch_ohlcv(sym, TF)
    feats = build_features(df).iloc[-WINDOW_BARS:]
    fr = df["close"].pct_change().shift(-1).reindex(feats.index).fillna(0.0)
    y = np.asarray(label_signals(fr, threshold=THR))
    feats, y = feats.iloc[:-1], y[:-1]
    dates = [pd.Timestamp(t).date() for t in pd.to_datetime(feats.index)]
    start_iso = pd.Timestamp(feats.index[0]).strftime("%Y-%m-%dT00:00:00Z")
    end_iso = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    news = fetch_news(sym, start_iso, end_iso)
    n_news_total += len(news)
    if news:
        nd = pd.DataFrame(news, columns=["ts", "text"])
        nd["date"] = [pd.Timestamp(t).date() for t in nd["ts"]]
        nd["pol"] = polarity(nd["text"].tolist())
        daily = nd.groupby("date")["pol"].mean().to_dict()
    else:
        daily = {}
    sent = pd.Series([daily.get(d, np.nan) for d in dates]).ffill().fillna(0.0).values
    aug = feats.copy(); aug["news_sent"] = sent

    k = int(len(feats) * 0.8)
    base_tr_X.append(feats.iloc[:k]); base_tr_y.append(y[:k]); base_v_X.append(feats.iloc[k:]); base_v_y.append(y[k:])
    aug_tr_X.append(aug.iloc[:k]); aug_v_X.append(aug.iloc[k:])

bX, by = pd.concat(base_tr_X), np.concatenate(base_tr_y)
bvX, bvy = pd.concat(base_v_X), np.concatenate(base_v_y)
aX, avX = pd.concat(aug_tr_X), pd.concat(aug_v_X)

b3, (bd, bn) = _oos(bX, by, bvX, bvy)
a3, (ad, an) = _oos(aX, by, avX, bvy)
fb = f"{bd:.3f}" if bd is not None else "n/a"; fa = f"{ad:.3f}" if ad is not None else "n/a"
print(f"news headlines fetched: {n_news_total}")
print(f"equity BASE oos_acc={b3:.3f} dir_acc={fb} (n~{bn})  |  +SENTIMENT oos_acc={a3:.3f} dir_acc={fa} (n~{an})")
