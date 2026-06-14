#!/usr/bin/env python
"""Per-strategy NET-of-cost edge — the measurement the live system never had.

`ml/strategy_weights.py` scores each strategy's directional edge, but only from
accumulated *live* `signal_history` — which doesn't exist until we deploy and
wait. This is the offline equivalent: it replays each rule-based strategy (and
the blended combiner) over historical bars and measures whether following it
actually makes money after transaction costs.

Method (no model fit → no train/test leakage; a clean walk-forward):
  - For each bar t, ask the strategy for a signal on the trailing window
    [t-LOOKBACK, t] — exactly what the live tick passes.
  - Hold position = sign(strength) into bar t+1 when |strength| > THRESHOLD,
    else flat. The bar's return is position * next_bar_return.
  - Charge the per-asset round-trip cost (ml/costs.py) whenever the position
    flips — so a strategy that flips every bar pays for it.
  - Pool bars across the universe and report hit rate, gross vs net mean return
    per traded bar, net annualized Sharpe, max drawdown, and trade frequency.

A strategy is "tradeable" only if its NET mean return per trade and NET Sharpe
are positive out of sample. Buy & hold is shown as the benchmark a long-only
strategy must beat.

Usage:
    cd apps/api
    PYTHONPATH=. .venv/bin/python scripts/strategy_edge_experiment.py
    PYTHONPATH=. .venv/bin/python scripts/strategy_edge_experiment.py --asset-class crypto
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from markets import get_market_adapter
from ml import costs
from ml.sequences import FeatureEngineer
from ml.strategies.combiner import _STRATEGY_FACTORIES, build_default_combiner

logging.basicConfig(level=logging.WARNING)

THRESHOLD = 0.1          # |strength| to take a position (matches combine_to_result)
LOOKBACK = 160           # trailing window passed to each strategy per bar
CRYPTO_DAYS = 90         # the live adapter caps 5m at 1 day — deep-fetch for research


def _deep_crypto(adapter, symbol: str, days: int) -> pd.DataFrame:
    """Paginate Coinbase 5m candles over `days` (the adapter's fetch_ohlcv caps
    5m at a single day, far too little to measure strategy edge)."""
    from datetime import timedelta

    product = adapter.normalize_symbol(symbol)
    end = adapter._now()
    start = end - timedelta(days=days)
    rows = adapter._fetch_paginated(product, start, end, 300)
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="s", utc=True)
    df = df.drop_duplicates(subset="ts").sort_values("ts").set_index("ts").astype(float)
    return df[["open", "high", "low", "close", "volume"]]

_UNIVERSE = {
    "equity": (["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "WMT"], "daily", 252),
    "crypto": (["BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", "AVAX-USD"], "5m", 365 * 24 * 12),
    "forex": (["EUR_USD", "GBP_USD", "AUD_USD", "USD_JPY", "USD_CAD"], "4h", 6 * 252),
}


def _signals_for_symbol(strategy, fe: pd.DataFrame, warmup: int):
    """Position series for one strategy over one symbol's feature frame.

    Returns (positions, next_returns) aligned per bar; position at t is held
    into t+1's return. The last bar is dropped (no forward return)."""
    close = fe["c"].to_numpy(dtype=float)
    n = len(fe)
    positions = np.zeros(n)
    for t in range(warmup, n):
        window = fe.iloc[max(0, t - LOOKBACK):t + 1]
        try:
            sig = strategy.generate_signal("SYM", window, float(close[t]))
            s = float(sig.strength)
        except Exception:
            s = 0.0
        positions[t] = (1.0 if s > THRESHOLD else (-1.0 if s < -THRESHOLD else 0.0))
    next_ret = np.zeros(n)
    next_ret[:-1] = close[1:] / np.where(close[:-1] != 0, close[:-1], 1.0) - 1.0
    # Drop the final bar (no realized forward return).
    return positions[:-1], next_ret[:-1]


def _blend_positions(combiner, fe: pd.DataFrame, warmup: int):
    close = fe["c"].to_numpy(dtype=float)
    n = len(fe)
    positions = np.zeros(n)
    for t in range(warmup, n):
        window = fe.iloc[max(0, t - LOOKBACK):t + 1]
        try:
            sig = combiner.combine_signals("SYM", window, float(close[t]))
            s = float(sig.strength)
        except Exception:
            s = 0.0
        positions[t] = (1.0 if s > THRESHOLD else (-1.0 if s < -THRESHOLD else 0.0))
    next_ret = np.zeros(n)
    next_ret[:-1] = close[1:] / np.where(close[:-1] != 0, close[:-1], 1.0) - 1.0
    return positions[:-1], next_ret[:-1]


def _score(pos_all, ret_all, asset_class, periods_per_year) -> dict:
    """Pool per-bar positions+returns across symbols → net-edge stats."""
    pos = np.concatenate(pos_all)
    ret = np.concatenate(ret_all)
    gross = pos * ret
    flips = np.abs(np.diff(np.concatenate([[0.0], pos]))) > 1e-9   # position changed
    net = gross - flips * costs.cost_frac(asset_class)

    traded = pos != 0
    n_traded = int(traded.sum())
    if n_traded == 0:
        return {"n_bars": len(pos), "n_traded": 0}
    wins = (np.sign(gross[traded]) > 0).sum()
    return {
        "n_bars": len(pos),
        "n_traded": n_traded,
        "pct_traded": n_traded / len(pos),
        "turnover": float(flips.sum() / len(pos)),
        "hit": wins / n_traded,
        "gross_bps": gross[traded].mean() * 1e4,
        "net_bps": net[traded].mean() * 1e4,
        "net_sharpe": costs.sharpe(net, periods_per_year) or 0.0,
        "net_total_pct": net.sum() * 100.0,
        "max_dd_pct": costs.max_drawdown(net) * 100.0,
    }


def run(asset_class: str) -> None:
    symbols, timeframe, ppy = _UNIVERSE[asset_class]
    adapter = get_market_adapter(asset_class)
    fe_engine = FeatureEngineer()

    frames: list[tuple[str, pd.DataFrame]] = []
    for s in symbols:
        try:
            df = _deep_crypto(adapter, s, CRYPTO_DAYS) if asset_class == "crypto" \
                else adapter.fetch_ohlcv(s, timeframe)
            fe = fe_engine.compute(df)
            if len(fe) > LOOKBACK + 50:
                frames.append((s, fe))
        except Exception as exc:
            print(f"  skip {s}: {exc}")
    if not frames:
        print(f"{asset_class}: no data")
        return
    warmup = 50
    total_bars = sum(len(fe) for _, fe in frames)
    print(f"\n=== {asset_class} ({timeframe}, {len(frames)} symbols, {total_bars} bars) "
          f"cost={costs.cost_bps(asset_class):.0f}bps round-trip ===")
    hdr = f"{'strategy':<16}{'trades':>8}{'hit%':>7}{'gross_bps':>10}{'net_bps':>9}{'net_sharpe':>11}{'turnover':>9}{'maxDD%':>8}"
    print(hdr)

    rows = []
    # Buy & hold benchmark (always long).
    bh_pos = [np.ones(len(fe) - 1) for _, fe in frames]
    bh_ret = []
    for _, fe in frames:
        c = fe["c"].to_numpy(dtype=float)
        bh_ret.append((c[1:] / np.where(c[:-1] != 0, c[:-1], 1.0) - 1.0))
    rows.append(("buy_hold", _score(bh_pos, bh_ret, asset_class, ppy)))

    # Each individual strategy.
    for name, factory in _STRATEGY_FACTORIES.items():
        if name == "ml":
            continue  # no model in research; measured separately
        strat = factory()
        pos_all, ret_all = [], []
        for _, fe in frames:
            p, r = _signals_for_symbol(strat, fe, warmup)
            pos_all.append(p); ret_all.append(r)
        rows.append((name, _score(pos_all, ret_all, asset_class, ppy)))

    # The blended combiner (what equity actually trades now).
    combiner = build_default_combiner(asset_class)
    bpos, bret = [], []
    for _, fe in frames:
        p, r = _blend_positions(combiner, fe, warmup)
        bpos.append(p); bret.append(r)
    rows.append(("BLEND", _score(bpos, bret, asset_class, ppy)))

    rows.sort(key=lambda kv: kv[1].get("net_sharpe", -99), reverse=True)
    for name, m in rows:
        if m.get("n_traded", 0) == 0:
            print(f"{name:<16}{'0':>8}  (never traded)")
            continue
        print(f"{name:<16}{m['n_traded']:>8}{m['hit']*100:>7.1f}{m['gross_bps']:>10.2f}"
              f"{m['net_bps']:>9.2f}{m['net_sharpe']:>11.2f}{m['turnover']:>9.3f}{m['max_dd_pct']:>8.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset-class", action="append", dest="acs",
                    help="repeatable; default equity,crypto,forex")
    args = ap.parse_args()
    for ac in (args.acs or ["equity", "crypto", "forex"]):
        try:
            run(ac)
        except Exception as exc:
            print(f"{ac}: FAILED — {exc}")


if __name__ == "__main__":
    main()
