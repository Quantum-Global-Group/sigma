#!/usr/bin/env python
"""Measured round — triple-barrier + meta-labeling vs the current baseline.

Compares four policies out-of-sample (purged walk-forward, net-of-cost) per asset:
  BASE  : current fixed-threshold ensemble (production baseline) — its 3-class
          prediction mapped to a side.
  COMB  : the live strategy-combiner side, every bar (the meta-labeling "primary").
  META  : COMB gated by a meta-model P(win) > tau  → HOLD otherwise.
  META* : META, additionally P(win)-sized (edge-proportional bet size).

PnL of a taken side s at bar t = triple_barrier_return(t)·s − round_trip_cost.
Reported: # bets (breadth), net total return, per-bet Sharpe, precision.
We adopt triple-barrier + meta-labeling only if META/META* beats BASE on net
Sharpe with adequate breadth — same discipline that rejected the prior rounds.

Causal/leak-free: combiner side at bar t uses only fe rows ≤ t; barriers look only
forward; train/test split is purged on the barrier-touch horizon.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/triple_barrier_experiment.py
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from sklearn.utils.class_weight import compute_sample_weight

from ml.costs import cost_frac, max_drawdown, sharpe
from ml.cv import purged_train_test_split
from ml.features import build_features
from ml.meta_label import MetaLabeler
from ml.models.base import label_signals
from ml.models.ensemble import EnsembleSignalModel
from ml.sequences import FeatureEngineer
from ml.strategies import build_default_combiner
from ml.triple_barrier import meta_bin, triple_barrier
from markets import get_market_adapter

ASSETS = {
    "equity": dict(symbols=["AAPL", "MSFT", "NVDA", "AMZN", "META"], tf="daily",
                   thr=0.005, pt=1.5, sl=1.5, vbar=10, band=0.1),
    "forex":  dict(symbols=["EUR_USD", "GBP_USD", "AUD_USD", "USD_JPY", "USD_CAD"], tf="4h",
                   thr=0.001, pt=1.5, sl=1.5, vbar=12, band=0.02),
    "crypto": dict(symbols=["BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", "AVAX-USD"], tf="5m",
                   thr=0.002, pt=1.5, sl=1.5, vbar=24, band=0.1),
}
WINDOW = 600     # cap bars/symbol so the per-bar combiner loop stays tractable
LB = 160         # bounded combiner lookback window (>= longest strategy lookback)
TAU = 0.55       # meta P(win) gate


def _combiner_sides(combiner, sym, fe, close):
    """Per-bar combiner strength/confidence using only past+current rows (causal)."""
    n = len(fe)
    strength = np.zeros(n)
    conf = np.zeros(n)
    for t in range(n):
        win = fe.iloc[max(0, t - LB):t + 1]
        try:
            sig = combiner.combine_signals(sym, win, float(close[t]), min_agreement=0)
            strength[t], conf[t] = sig.strength, sig.confidence
        except Exception:
            pass
    return strength, conf


def _build_symbol(asset, cfg, sym):
    adapter = get_market_adapter(asset)
    df = adapter.fetch_ohlcv(sym, cfg["tf"])
    if df is None or len(df) < 120:
        return None
    df = df.iloc[-WINDOW:]
    fe = FeatureEngineer().compute(df)
    close = fe["c"].to_numpy(dtype=float)
    atr = fe["atr"].to_numpy(dtype=float)
    target = np.clip(atr / np.where(close > 0, close, 1.0), 1e-4, None)

    # primary side from the live combiner
    combiner = build_default_combiner(asset)
    strength, conf = _combiner_sides(combiner, sym, fe, close)
    band = cfg["band"]
    side = np.where(strength > band, 1, np.where(strength < -band, -1, 0)).astype(int)

    # Causal meta feature: was the combiner directionally right on recent bars?
    # comb_right_j resolves at bar j+1, so a rolling mean shifted by 1 uses only
    # outcomes already known by bar t ("is the combiner on a hot streak?").
    ret1 = pd.Series(close).pct_change().shift(-1).fillna(0.0).to_numpy()
    comb_right = (np.sign(strength) == np.sign(ret1)).astype(float)
    recent_hit = pd.Series(comb_right).rolling(20).mean().shift(1).fillna(0.5).to_numpy()

    # triple-barrier outcomes (per bar)
    tb = triple_barrier(close, target, pt_mult=cfg["pt"], sl_mult=cfg["sl"], vbar_bars=cfg["vbar"])
    tb_ret = tb["ret"].to_numpy()
    t_touch = tb["t_touch"].to_numpy()

    # model features (build_features) aligned positionally to the capped df
    mf = build_features(df)
    pos = df.index.get_indexer(mf.index)
    valid = np.zeros(len(df), dtype=bool)
    valid[pos[pos >= 0]] = True
    ncols = mf.shape[1]
    feat = np.full((len(df), ncols), np.nan)
    feat[pos[pos >= 0]] = mf.to_numpy()[pos >= 0]

    # baseline fixed-threshold next-bar labels
    nxt = pd.Series(close).pct_change().shift(-1).fillna(0.0).to_numpy()
    ybase = label_signals(pd.Series(nxt), threshold=cfg["thr"])

    # usable events: complete features AND forward window exists
    ev = np.where(valid & (np.arange(len(df)) < len(df) - 1))[0]
    return dict(
        feat=feat, fcols=list(mf.columns), ybase=ybase, side=side, strength=strength,
        conf=conf, tb_ret=tb_ret, t_touch=t_touch, ev=ev, recent_hit=recent_hit,
    )


def _policy(tb_ret, side, asset, sizing=None):
    taken = side != 0
    if taken.sum() == 0:
        return dict(n=0, net=0.0, sharpe=None, prec=None, mdd=None)
    pnl = tb_ret[taken] * np.sign(side[taken])
    f = np.ones(taken.sum()) if sizing is None else sizing[taken]
    pnl = f * pnl - f * cost_frac(asset)
    return dict(n=int(taken.sum()), net=float(pnl.sum()),
                sharpe=sharpe(pnl, periods_per_year=1), prec=float((pnl > 0).mean()),
                mdd=max_drawdown(pnl))


META_COLS_EXTRA = ["strength", "conf", "side", "abs_strength", "recent_hit"]
TAU_GRID = [0.50, 0.55, 0.60, 0.65]


def _meta_matrix(feat, strength, conf, side, recent_hit):
    return np.column_stack([
        feat, strength, conf, side.astype(float), np.abs(strength), recent_hit,
    ])


def run_asset(asset, cfg):
    Xb_tr, yb_tr = [], []
    Xm_tr, ym_tr = [], []
    te_feat, te_side, te_str, te_conf, te_rh, te_tbret = [], [], [], [], [], []
    fcols = None
    for sym in cfg["symbols"]:
        d = _build_symbol(asset, cfg, sym)
        if d is None or len(d["ev"]) < 60:
            continue
        ev = d["ev"]
        tr_i, te_i = purged_train_test_split(
            ev.astype(float), d["t_touch"][ev].astype(float), test_frac=0.2, embargo_frac=0.01)
        tr, te = ev[tr_i], ev[te_i]
        if len(tr) < 40 or len(te) < 10:
            continue
        fcols = d["fcols"]

        Xb_tr.append(d["feat"][tr]); yb_tr.append(d["ybase"][tr])
        side_tr = d["side"][tr]
        win_tr = meta_bin(d["tb_ret"][tr], side_tr)
        take = side_tr != 0
        if take.sum() > 0:
            xm = _meta_matrix(d["feat"][tr], d["strength"][tr], d["conf"][tr], side_tr, d["recent_hit"][tr])
            Xm_tr.append(xm[take]); ym_tr.append(win_tr[take])

        te_feat.append(d["feat"][te]); te_side.append(d["side"][te])
        te_str.append(d["strength"][te]); te_conf.append(d["conf"][te])
        te_rh.append(d["recent_hit"][te]); te_tbret.append(d["tb_ret"][te])

    if not te_feat or fcols is None:
        print(f"{asset:6} insufficient data"); return
    Xb = np.vstack(Xb_tr); yb = np.concatenate(yb_tr)
    TEf = np.vstack(te_feat); TEside = np.concatenate(te_side)
    TEstr = np.concatenate(te_str); TEconf = np.concatenate(te_conf)
    TErh = np.concatenate(te_rh); TEret = np.concatenate(te_tbret)
    cols = fcols + META_COLS_EXTRA

    # BASE: fixed-threshold ensemble → side
    ens = EnsembleSignalModel(); ens.feature_names = fcols
    sw = compute_sample_weight("balanced", yb)
    ens.rf.fit(Xb, yb, sample_weight=sw); ens.xgb.fit(Xb, yb, sample_weight=sw)
    pred = np.argmax((ens.rf.predict_proba(TEf) + ens.xgb.predict_proba(TEf)) / 2, axis=1)
    side_base = np.where(pred == 2, 1, np.where(pred == 0, -1, 0))

    # META: train meta-model on richer features; gate + size the combiner side
    if Xm_tr:
        meta = MetaLabeler().train(pd.DataFrame(np.vstack(Xm_tr), columns=cols), np.concatenate(ym_tr))
        Xm_te = pd.DataFrame(_meta_matrix(TEf, TEstr, TEconf, TEside, TErh), columns=cols)
        pwin = meta.predict_proba_win(Xm_te)
    else:
        pwin = np.full(len(TEside), 0.5)

    def fmt(m):
        s = f"{m['sharpe']:.3f}" if m["sharpe"] is not None else "n/a"
        p = f"{m['prec']:.3f}" if m["prec"] is not None else "n/a"
        dd = f"{m['mdd']:.4f}" if m.get("mdd") is not None else "n/a"
        return f"n={m['n']:4d} net={m['net']:+.4f} sharpe={s} prec={p} mdd={dd}"

    print(f"{asset:6} BASE       {fmt(_policy(TEret, side_base, asset))}")
    print(f"{asset:6} COMB       {fmt(_policy(TEret, TEside, asset))}")
    print(f"{asset:6} COMB_FLIP  {fmt(_policy(TEret, -TEside, asset))}  (diagnostic)")
    for tau in TAU_GRID:
        side_meta = np.where((TEside != 0) & (pwin > tau), TEside, 0)
        size = np.clip((pwin - 0.5) * 2.0, 0.0, 1.0)
        g = _policy(TEret, side_meta, asset)
        s = _policy(TEret, side_meta, asset, sizing=size)
        print(f"{asset:6} META@{tau:.2f}  {fmt(g)}   META*  {fmt(s)}")


def main():
    for _asset, _cfg in ASSETS.items():
        try:
            run_asset(_asset, _cfg)
        except Exception as exc:
            print(f"{_asset:6} ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
