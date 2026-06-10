#!/usr/bin/env python
"""Diagnostic — is the forex 4h combiner side inverted, and which strategy causes it?

The triple-barrier round found the combiner's forex side appears inverted on a thin
(n=29) test split: taking the OPPOSITE side won ~69%. This verifies that on the FULL
sample across MANY pairs and breaks directional hit-rate down PER STRATEGY (via the
combiner's component_signals), so we can pinpoint the culprit(s) rather than guess.

Directional hit-rate = P(sign(strategy_strength) == sign(next-bar return)) over bars
where the strategy has an opinion. <0.5 ⇒ that strategy is anti-predictive (inverted)
on 4h. Causal: side at bar t uses only fe rows ≤ t; outcome is the next bar.

Usage: cd apps/api && PYTHONPATH=. .venv/bin/python scripts/forex_inversion_check.py
"""
from __future__ import annotations

import os
import sys
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from ml.sequences import FeatureEngineer
from ml.strategies import build_default_combiner
from markets import get_market_adapter

PAIRS = ["EUR_USD", "GBP_USD", "AUD_USD", "USD_JPY", "USD_CAD",
         "NZD_USD", "USD_CHF", "EUR_GBP", "EUR_JPY", "GBP_JPY"]
TF = "4h"
MAXBARS = 1500    # cap per pair for runtime; plenty for statistics
LB = 160


def _hit(side_sign, fwd_sign):
    """(#opinions, #hits) for directional agreement, ignoring flat bars."""
    m = (side_sign != 0) & (fwd_sign != 0)
    return int(m.sum()), int(((side_sign == fwd_sign) & m).sum())


def main():
    combiner = build_default_combiner("forex")
    strat_n = defaultdict(int)
    strat_hit = defaultdict(int)
    comb_n = comb_hit = 0
    pairs_used = 0

    for sym in PAIRS:
        try:
            df = get_market_adapter("forex").fetch_ohlcv(sym, TF)
        except Exception as exc:
            print(f"skip {sym}: {exc}")
            continue
        if df is None or len(df) < 200:
            continue
        df = df.iloc[-MAXBARS:]
        fe = FeatureEngineer().compute(df)
        close = fe["c"].to_numpy(dtype=float)
        fwd = np.sign(np.append(np.diff(close), 0.0))    # next-bar direction
        n = len(fe)
        pairs_used += 1

        comb_sign = np.zeros(n)
        comp_sign: dict[str, np.ndarray] = {}
        for t in range(n - 1):                            # last bar has no forward return
            win = fe.iloc[max(0, t - LB):t + 1]
            try:
                sig = combiner.combine_signals(sym, win, float(close[t]), min_agreement=0)
            except Exception:
                continue
            comb_sign[t] = np.sign(sig.strength)
            for name, st in (sig.metadata or {}).get("component_signals", {}).items():
                if name not in comp_sign:
                    comp_sign[name] = np.zeros(n)
                comp_sign[name][t] = np.sign(st)

        cn, ch = _hit(comb_sign, fwd)
        comb_n += cn; comb_hit += ch
        for name, ssign in comp_sign.items():
            sn, sh = _hit(ssign, fwd)
            strat_n[name] += sn; strat_hit[name] += sh
        cprec = ch / cn if cn else float("nan")
        print(f"{sym:8} bars={n:5d} combiner_prec={cprec:.3f} (n={cn})")

    print(f"\n=== FOREX 4h directional hit-rate over {pairs_used} pairs ===")
    if comb_n:
        print(f"COMBINER     n={comb_n:6d} prec={comb_hit / comb_n:.3f} "
              f"flip={(comb_n - comb_hit) / comb_n:.3f}")
    print("per-strategy (prec <0.5 ⇒ inverted/anti-predictive on 4h):")
    for name in sorted(strat_n, key=lambda k: strat_hit[k] / max(1, strat_n[k])):
        n_ = strat_n[name]
        if n_ == 0:
            continue
        print(f"  {name:16} n={n_:6d} prec={strat_hit[name] / n_:.3f}")


if __name__ == "__main__":
    main()
