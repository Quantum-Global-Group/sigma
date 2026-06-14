#!/usr/bin/env python
"""Thesis 1 — event-driven news drift. Different in KIND from price signals.

Unit of analysis = a news event, not every bar. Hypothesis: after a sentiment-laden
catalyst, price under-reacts and drifts in the sentiment's direction over the next
few bars (post-news drift). We measure that drift with the same apparatus that
killed the price strategies — triple-barrier forward returns, net of cost, judged
on a held-out tail (ml/edge_eval.py).

Strictly lookahead-safe: a signal on day D is entered at D+1's close, using only
news with created_at <= D. FinBERT scores are cached per symbol so reruns are fast.

Reports, on the HOLD-OUT only:
  baseline(all)         every sentiment day, side = sign(daily sentiment)
  strong-sentiment      |sentiment| above the train median
  meta-gated            MetaLabeler(event features) -> P(profitable), take top
Each lands an ml/edge_eval verdict (PASS needs net-positive, positive Sharpe, ≥100 trades).

Usage:
    cd apps/api
    PYTHONPATH=. .venv/bin/python scripts/event_drift_experiment.py
    PYTHONPATH=. .venv/bin/python scripts/event_drift_experiment.py --symbols AAPL NVDA TSLA
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets import get_market_adapter
from ml import costs, edge_eval
from ml.news import fetch_news_cached
from ml.triple_barrier import side_pnl, triple_barrier

logging.basicConfig(level=logging.WARNING)

LIQUID = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOG", "AMD", "JPM", "NFLX"]
VBAR = 5            # drift horizon in trading days
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
    """{date: (mean_polarity, headline_count)} for a symbol, cached (FinBERT is slow)."""
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


def build_trades(symbol: str, adapter):
    """Per-event trades for a symbol: (entry_ts, side, realized_ret, features)."""
    df = adapter.fetch_ohlcv(symbol, "daily")
    if df is None or len(df) < 120:
        return None
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    # ATR/price as the volatility-scaled barrier width.
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    atr = pd.Series(np.concatenate([[tr[0]], tr])).rolling(14, min_periods=1).mean().to_numpy()
    target = np.clip(atr / np.where(close > 0, close, 1.0), 1e-4, None)

    start_iso = pd.Timestamp(df.index[0]).strftime("%Y-%m-%dT00:00:00Z")
    sent = daily_sentiment(symbol, start_iso)
    if not sent:
        return None

    dates = [str(pd.Timestamp(t).date()) for t in df.index]
    pol = pd.Series([sent.get(d, (np.nan, 0))[0] for d in dates])
    cnt = pd.Series([float(sent.get(d, (np.nan, 0))[1]) for d in dates]).fillna(0.0)
    # lookahead-safe engineered context (rolling, shifted by construction below)
    rm, rs = pol.rolling(20, min_periods=5).mean(), pol.rolling(20, min_periods=5).std()
    surprise = ((pol - rm) / rs.replace(0, np.nan)).fillna(0.0).to_numpy()
    cm, cs = cnt.rolling(20, min_periods=5).mean(), cnt.rolling(20, min_periods=5).std()
    cov_z = ((cnt - cm) / cs.replace(0, np.nan)).fillna(0.0).to_numpy()
    pol = pol.to_numpy()

    rows = []
    n = len(df)
    for d in range(20, n - VBAR - 1):
        if np.isnan(pol[d]) or abs(pol[d]) < 1e-9:
            continue
        entry = d + 1                       # enter NEXT bar — strictly after the news day
        side = 1 if pol[d] > 0 else -1
        tb = triple_barrier(close, target, pt_mult=PT, sl_mult=SL, vbar_bars=VBAR,
                            t_events=[entry])
        ret = float(side_pnl(tb["ret"].to_numpy(), [side])[0])
        rows.append((pd.Timestamp(df.index[entry]).value, side, ret,
                     pol[d], abs(pol[d]), surprise[d], cov_z[d], cnt[d]))
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["ts", "side", "ret", "pol", "abs_pol",
                                       "surprise", "cov_z", "count"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=LIQUID)
    args = ap.parse_args()

    adapter = get_market_adapter("equity")
    parts = []
    for s in args.symbols:
        try:
            t = build_trades(s, adapter)
            if t is not None:
                parts.append(t)
                print(f"  {s}: {len(t)} event-trades")
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    if not parts:
        print("no trades"); return
    T = pd.concat(parts, ignore_index=True)
    cf = costs.cost_frac("equity")

    train, test = edge_eval.chrono_split(T["ts"].to_numpy(), TRAIN_FRAC)
    tr, te = T[train], T[test]
    print(f"\n=== event-driven news drift: {len(T)} trades "
          f"({train.sum()} train / {test.sum()} test), VBAR={VBAR}d, cost {cf*1e4:.0f}bps ===")

    # 1) baseline: every sentiment day, side = sign(sentiment)
    base = edge_eval.trade_stats(te["ret"].to_numpy(), cost_frac=cf)
    print(edge_eval.format_row("baseline(all)", base))

    # 2) strong sentiment: |pol| above the TRAIN median (threshold fit on train only)
    thr = float(tr["abs_pol"].median())
    strong = te[te["abs_pol"] > thr]
    print(edge_eval.format_row(f"strong|pol|>{thr:.2f}", edge_eval.trade_stats(strong["ret"].to_numpy(), cost_frac=cf)))

    # 3) learned gate: MetaLabeler(event features) -> P(profitable), trained on train
    from ml.meta_label import MetaLabeler
    feat_cols = ["pol", "abs_pol", "surprise", "cov_z", "count"]
    y_tr = (tr["ret"].to_numpy() > cf).astype(int)   # profitable after cost
    meta = MetaLabeler().train(tr[feat_cols], y_tr)
    p_te = meta.predict_proba_win(te[feat_cols])
    for tau in (0.50, 0.55, 0.60):
        keep = te[p_te > tau]
        print(edge_eval.format_row(f"meta>{tau:.2f}", edge_eval.trade_stats(keep["ret"].to_numpy(), cost_frac=cf)))

    # --- ALPHA vs BETA: the decisive check ---------------------------------
    # In an up-market, "positive news -> long" can just harvest beta. Two tests:
    #  (a) side split — a real drift makes money on BOTH long (good news up) and
    #      short (bad news down); beta only shows up on the long side.
    #  (b) market-neutral — subtract side*SPY drift over the same window; if the
    #      strong-sentiment edge survives, it is alpha, not market exposure.
    print("\n  ALPHA vs BETA (held-out):")
    longs = te[te["side"] > 0]
    shorts = te[te["side"] < 0]
    print(edge_eval.format_row("long-only", edge_eval.trade_stats(longs["ret"].to_numpy(), cost_frac=cf)))
    print(edge_eval.format_row("short-only", edge_eval.trade_stats(shorts["ret"].to_numpy(), cost_frac=cf)))

    spy = adapter.fetch_ohlcv("SPY", "daily")
    sc = spy["close"].astype(float)
    spy_fwd = (sc.shift(-VBAR) / sc - 1.0)               # SPY's VBAR-day forward return
    spy_by_ns = {pd.Timestamp(t).value: float(v) for t, v in spy_fwd.items()}
    def _excess(frame):
        m = frame["ts"].map(spy_by_ns).fillna(0.0).to_numpy()
        return frame["ret"].to_numpy() - frame["side"].to_numpy() * m   # remove beta-1 market move
    mn_base = edge_eval.trade_stats(_excess(te), cost_frac=cf)
    mn_strong = edge_eval.trade_stats(_excess(strong), cost_frac=cf)
    print(edge_eval.format_row("mkt-neutral all", mn_base))
    print(edge_eval.format_row("mkt-neutral strong", mn_strong))

    print()
    print(edge_eval.verdict("event-drift baseline", base))
    print(edge_eval.verdict("event-drift strong", edge_eval.trade_stats(strong["ret"].to_numpy(), cost_frac=cf)))
    print(edge_eval.verdict("market-neutral strong", mn_strong))


if __name__ == "__main__":
    main()
