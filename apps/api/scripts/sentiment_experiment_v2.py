#!/usr/bin/env python
"""Engineered equity sentiment round (v2).

Over v1's same-day mean polarity, this adds lookahead-safe engineered features:
  sent_mean    - carry-forward same-day mean polarity (v1 baseline feature)
  sent_ewm     - decay-weighted sentiment (EWM halflife 2 over bar-aligned series)
  sent_surprise- z-score of today's sentiment vs its own rolling 20-bar mean/std
  cov_log      - log1p(headline count) that day  (coverage level)
  cov_z        - z-score of headline count vs rolling 20-bar mean/std (coverage spike)

All features at bar D use only news with created_at<=D (no lookahead). FinBERT scores
are cached per symbol so reruns are instant. Walk-forward (chronological, per-symbol)
OOS comparison: base vs base+engineered. Adopt only if it beats base.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/sentiment_experiment_v2.py
"""
from __future__ import annotations
import sys, os, json, warnings, datetime as dt
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
WINDOW_BARS = 320
CACHE = "/tmp/sigma_sent_cache"
HDR = {"APCA-API-KEY-ID": settings.alpaca_api_key, "APCA-API-SECRET-KEY": settings.alpaca_secret}
ENG = ["sent_mean", "sent_ewm", "sent_surprise", "cov_log", "cov_z"]

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
    clf, out = _finbert(), []
    for i in range(0, len(texts), 64):
        for scores in clf(texts[i:i + 64], batch_size=64):
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

def daily_agg(symbol, start_iso, end_iso):
    """Return {date_str: (mean_polarity, count)}, cached per symbol+window."""
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, f"{symbol}_{start_iso[:10]}.json")
    if os.path.exists(key):
        return {k: tuple(v) for k, v in json.load(open(key)).items()}
    news = fetch_news(symbol, start_iso, end_iso)
    if not news:
        json.dump({}, open(key, "w")); return {}
    nd = pd.DataFrame(news, columns=["ts", "text"])
    nd["date"] = [str(pd.Timestamp(t).date()) for t in nd["ts"]]
    nd["pol"] = polarity(nd["text"].tolist())
    g = nd.groupby("date")["pol"].agg(["mean", "count"])
    out = {d: (float(r["mean"]), int(r["count"])) for d, r in g.iterrows()}
    json.dump(out, open(key, "w"))
    return out

def engineered(dates, agg):
    """Lookahead-safe engineered features aligned to bar `dates` (list of date)."""
    means = pd.Series([agg.get(str(d), (np.nan, 0))[0] for d in dates]).ffill().fillna(0.0)
    counts = pd.Series([float(agg.get(str(d), (np.nan, 0))[1]) for d in dates]).fillna(0.0)
    ewm = means.ewm(halflife=2, adjust=False).mean()
    rm, rs = means.rolling(20, min_periods=5).mean(), means.rolling(20, min_periods=5).std()
    surprise = ((means - rm) / rs.replace(0, np.nan)).fillna(0.0)
    cm, cs = counts.rolling(20, min_periods=5).mean(), counts.rolling(20, min_periods=5).std()
    cov_z = ((counts - cm) / cs.replace(0, np.nan)).fillna(0.0)
    return pd.DataFrame({
        "sent_mean": means.values, "sent_ewm": ewm.values, "sent_surprise": surprise.values,
        "cov_log": np.log1p(counts.values), "cov_z": cov_z.values,
    })

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
btrX, btry, bvX, bvy, atrX, avX = [], [], [], [], [], []
n_news = 0
for sym in SYMBOLS:
    df = adapter.fetch_ohlcv(sym, TF)
    feats = build_features(df).iloc[-WINDOW_BARS:]
    fr = df["close"].pct_change().shift(-1).reindex(feats.index).fillna(0.0)
    y = np.asarray(label_signals(fr, threshold=THR))
    feats, y = feats.iloc[:-1], y[:-1]
    dates = [pd.Timestamp(t).date() for t in pd.to_datetime(feats.index)]
    start_iso = pd.Timestamp(feats.index[0]).strftime("%Y-%m-%dT00:00:00Z")
    agg = daily_agg(sym, start_iso, dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
    n_news += sum(c for _, c in agg.values())
    eng = engineered(dates, agg)
    aug = feats.copy()
    for col in ENG:
        aug[col] = eng[col].values

    k = int(len(feats) * 0.8)
    btrX.append(feats.iloc[:k]); btry.append(y[:k]); bvX.append(feats.iloc[k:]); bvy.append(y[k:])
    atrX.append(aug.iloc[:k]); avX.append(aug.iloc[k:])

bX, by = pd.concat(btrX), np.concatenate(btry)
bvX_, bvy_ = pd.concat(bvX), np.concatenate(bvy)
aX, avX_ = pd.concat(atrX), pd.concat(avX)

b3, (bd, bn) = _oos(bX, by, bvX_, bvy_)
a3, (ad, an) = _oos(aX, by, avX_, bvy_)
fb = f"{bd:.3f}" if bd is not None else "n/a"; fa = f"{ad:.3f}" if ad is not None else "n/a"
print(f"news headlines: {n_news}  engineered features: {ENG}")
print(f"equity BASE      oos_acc={b3:.3f} dir_acc={fb} (n~{bn})")
print(f"equity +ENG_SENT oos_acc={a3:.3f} dir_acc={fa} (n~{an})")
