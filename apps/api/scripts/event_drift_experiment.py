#!/usr/bin/env python
"""Thesis 1 — event-driven news drift, with the alpha-vs-beta acid test.

Unit of analysis = a news event, not a bar. Hypothesis: after a sentiment-laden
catalyst, price under-reacts and drifts in the sentiment's direction. Measured
with the same apparatus that killed the price strategies — triple-barrier forward
returns, net of cost, judged on a held-out tail (ml/edge_eval.py).

The headline raw edge is ~half beta (in an up-market, "good news -> long" harvests
beta). Two defenses, both reported:
  * per-name market-neutral — subtract sideᵢ·βᵢ·(SPY return over the SAME hold),
    with βᵢ estimated on TRAIN only. Removes each name's actual market exposure.
  * an out-of-regime window (--start/--end) — does the residual survive a period
    that includes a bear market (2018–2021 incl. the 2020 crash)? If it only
    works in a bull window, it was regime/beta, not alpha.

Strictly lookahead-safe: signal on day D (news created_at ≤ D), entered at D+1's
close; β and thresholds fit on train only. FinBERT scores cache per (symbol,
window) so reruns are fast.

Usage:
    cd apps/api
    PYTHONPATH=. .venv/bin/python scripts/event_drift_experiment.py                       # recent ~2y
    PYTHONPATH=. .venv/bin/python scripts/event_drift_experiment.py --start 2018-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets import get_market_adapter
from markets.equity_data import fetch_equity_ohlcv
from ml import costs, edge_eval
from ml.news import fetch_news_cached
from ml.triple_barrier import side_pnl, triple_barrier

logging.basicConfig(level=logging.WARNING)

LIQUID = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOG", "AMD", "JPM", "NFLX"]
VBAR = 5
PT = SL = 1.5
TRAIN_FRAC = 0.6
SENT_CACHE = "/tmp/sigma_sent_daily"

_clf = None


def _finbert():
    global _clf
    if _clf is None:
        from transformers import pipeline
        _clf = pipeline("sentiment-analysis", model="ProsusAI/finbert",
                        top_k=None, device=-1, truncation=True)
    return _clf


def _polarity(texts: list[str]) -> list[float]:
    if not texts:
        return []
    clf, out = _finbert(), []
    for i in range(0, len(texts), 64):
        for scores in clf(texts[i:i + 64], batch_size=64):
            d = {s["label"].lower(): s["score"] for s in scores}
            out.append(float(d.get("positive", 0) - d.get("negative", 0)))
    return out


def daily_sentiment(symbol: str, start_iso: str) -> dict[str, tuple[float, int]]:
    os.makedirs(SENT_CACHE, exist_ok=True)
    key = os.path.join(SENT_CACHE, f"{symbol}_{start_iso[:10]}.json")
    if os.path.exists(key):
        return {k: tuple(v) for k, v in json.load(open(key)).items()}
    events = fetch_news_cached(symbol, start_iso)
    if not events:
        json.dump({}, open(key, "w")); return {}
    df = pd.DataFrame({"date": [str(pd.Timestamp(e.ts).date()) for e in events],
                       "text": [e.text for e in events]})
    df["pol"] = _polarity(df["text"].tolist())
    g = df.groupby("date")["pol"].agg(["mean", "count"])
    out = {d: (float(r["mean"]), int(r["count"])) for d, r in g.iterrows()}
    json.dump(out, open(key, "w"))
    return out


def _atr_target(df):
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    atr = pd.Series(np.concatenate([[tr[0]], tr])).rolling(14, min_periods=1).mean().to_numpy()
    return np.clip(atr / np.where(close > 0, close, 1.0), 1e-4, None)


def build_trades(symbol, spy_close, start, end):
    df = fetch_equity_ohlcv(symbol, "daily", start=start) if start \
        else get_market_adapter("equity").fetch_ohlcv(symbol, "daily")
    if df is None or len(df) < 150:
        return None
    if start:
        df = df.loc[start:end] if end else df.loc[start:]
    if len(df) < 150:
        return None
    close = df["close"].to_numpy(dtype=float)
    target = _atr_target(df)

    # per-name beta on the TRAIN slice (first TRAIN_FRAC of this symbol's bars)
    spy = spy_close.reindex(df.index).ffill()
    sret = spy.pct_change().to_numpy()
    iret = df["close"].pct_change().to_numpy()
    cut0 = int(len(df) * TRAIN_FRAC)
    sv, iv = sret[1:cut0], iret[1:cut0]
    m = np.isfinite(sv) & np.isfinite(iv)
    var = float(np.var(sv[m])) if m.sum() > 30 else 0.0
    beta = float(np.cov(iv[m], sv[m])[0, 1] / var) if var > 0 else 1.0
    beta = float(np.clip(beta, 0.0, 3.0))
    spy_arr = spy.to_numpy(dtype=float)

    start_iso = pd.Timestamp(df.index[0]).strftime("%Y-%m-%dT00:00:00Z")
    sent = daily_sentiment(symbol, start_iso)
    if not sent:
        return None
    dates = [str(pd.Timestamp(t).date()) for t in df.index]
    pol = pd.Series([sent.get(d, (np.nan, 0))[0] for d in dates])
    cnt = pd.Series([float(sent.get(d, (np.nan, 0))[1]) for d in dates]).fillna(0.0)
    rm, rs = pol.rolling(20, min_periods=5).mean(), pol.rolling(20, min_periods=5).std()
    surprise = ((pol - rm) / rs.replace(0, np.nan)).fillna(0.0).to_numpy()
    cm, cs = cnt.rolling(20, min_periods=5).mean(), cnt.rolling(20, min_periods=5).std()
    cov_z = ((cnt - cm) / cs.replace(0, np.nan)).fillna(0.0).to_numpy()
    pol = pol.to_numpy()

    rows, n = [], len(df)
    for d in range(20, n - VBAR - 1):
        if np.isnan(pol[d]) or abs(pol[d]) < 1e-9:
            continue
        entry = d + 1
        side = 1 if pol[d] > 0 else -1
        tb = triple_barrier(close, target, pt_mult=PT, sl_mult=SL, vbar_bars=VBAR, t_events=[entry])
        ret = float(side_pnl(tb["ret"].to_numpy(), [side])[0])
        touch = int(tb["t_touch"].to_numpy()[0])
        # per-name market-neutral: remove sideᵢ·βᵢ·(SPY move over the ACTUAL hold)
        sp0, sp1 = spy_arr[entry], spy_arr[min(touch, n - 1)]
        spy_move = (sp1 / sp0 - 1.0) if (sp0 and np.isfinite(sp0) and np.isfinite(sp1)) else 0.0
        mn_ret = ret - side * beta * spy_move
        rows.append((pd.Timestamp(df.index[entry]).value, side, ret, mn_ret,
                     abs(pol[d]), surprise[d], cov_z[d], cnt[d]))
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["ts", "side", "ret", "mn_ret",
                                       "abs_pol", "surprise", "cov_z", "count"])


def _bucket_report(label, te, tr, col, cf):
    base = edge_eval.trade_stats(te[col].to_numpy(), cost_frac=cf)
    print(edge_eval.format_row(f"{label} all", base))
    thr = float(tr["abs_pol"].median())
    strong = te[te["abs_pol"] > thr]
    s_stats = edge_eval.trade_stats(strong[col].to_numpy(), cost_frac=cf)
    print(edge_eval.format_row(f"{label} strong", s_stats))
    return base, s_stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=LIQUID)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    spy_df = fetch_equity_ohlcv("SPY", "daily", start=args.start) if args.start else \
        __import__("markets", fromlist=["get_market_adapter"]).get_market_adapter("equity").fetch_ohlcv("SPY", "daily")
    spy_close = spy_df["close"].astype(float)

    parts = []
    for s in args.symbols:
        try:
            t = build_trades(s, spy_close, args.start, args.end)
            if t is not None:
                parts.append(t)
                print(f"  {s}: {len(t)} event-trades (β-neutralized)")
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    if not parts:
        print("no trades"); return
    T = pd.concat(parts, ignore_index=True)
    cf = costs.cost_frac("equity")
    train, test = edge_eval.chrono_split(T["ts"].to_numpy(), TRAIN_FRAC)
    tr, te = T[train], T[test]
    window = f"{args.start or 'recent'}..{args.end or 'now'}"
    print(f"\n=== event-driven news drift [{window}]: {len(T)} trades "
          f"({train.sum()} train / {test.sum()} test), VBAR={VBAR}d, cost {cf*1e4:.0f}bps ===")

    print("  RAW (contains beta):")
    raw_base, raw_strong = _bucket_report("raw", te, tr, "ret", cf)
    print("  PER-NAME MARKET-NEUTRAL (β fit on train):")
    mn_base, mn_strong = _bucket_report("mn", te, tr, "mn_ret", cf)

    print()
    print(edge_eval.verdict("raw strong", raw_strong))
    print(edge_eval.verdict("market-neutral strong", mn_strong))


if __name__ == "__main__":
    main()
