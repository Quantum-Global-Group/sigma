"""Triple-barrier labeling (López de Prado, *Advances in Financial ML* ch. 3).

Replaces fixed-threshold next-bar labels with *tradeable* outcomes. For each event
bar we set three barriers and label by whichever is touched first:

  * upper (profit-take) = price · (1 + pt_mult · target)   → label +1
  * lower (stop-loss)   = price · (1 − sl_mult · target)   → label −1
  * vertical (time)     = `vbar_bars` bars later           → label sign(return)

`target` is a *fractional* width per bar (e.g. ATR/price or rolling return vol), so
barriers self-scale with volatility — a 0.5% move in a calm regime is not equated
with 0.5% in chaos. The realized return at first touch is recorded, which is what a
cost-aware PnL/Sharpe evaluation and the meta-label (`meta_bin`) consume.

Strictly causal: an event at bar i looks only at bars i+1 … i+vbar_bars. All
functions are pure and unit-tested (incl. an explicit no-lookahead assertion).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

_HIT_PT, _HIT_SL, _HIT_VBAR = "pt", "sl", "vbar"


def triple_barrier(
    close: Sequence[float],
    target: Sequence[float],
    *,
    pt_mult: float = 1.0,
    sl_mult: float = 1.0,
    vbar_bars: int = 10,
    t_events: Sequence[int] | None = None,
    min_width: float = 1e-6,
) -> pd.DataFrame:
    """Label each event bar by first-touched barrier.

    Returns a DataFrame indexed by event position with columns:
      label   ∈ {-1, 0, 1}  — directional outcome (0 only if vertical touch is flat)
      ret     float          — realized return from event close to first-touch close
      t_touch int            — position of the first-touch bar
      hit     str            — 'pt' | 'sl' | 'vbar'
      bars    int            — bars held (t_touch − event)
    """
    c = np.asarray(close, dtype=float)
    w = np.asarray(target, dtype=float)
    n = len(c)
    events = np.arange(n) if t_events is None else np.asarray(t_events, dtype=int)

    labels = np.zeros(len(events), dtype=int)
    rets = np.zeros(len(events), dtype=float)
    touch = np.zeros(len(events), dtype=int)
    hits: list[str] = []

    for k, i in enumerate(events):
        p0 = c[i]
        width = w[i] if (w[i] is not None and w[i] > 0 and np.isfinite(w[i])) else min_width
        up = p0 * (1.0 + pt_mult * width)
        dn = p0 * (1.0 - sl_mult * width)
        end = min(i + vbar_bars, n - 1)

        tt, h = end, _HIT_VBAR
        for j in range(i + 1, end + 1):
            if c[j] >= up:
                tt, h = j, _HIT_PT
                break
            if c[j] <= dn:
                tt, h = j, _HIT_SL
                break

        r = (c[tt] - p0) / p0 if p0 != 0 else 0.0
        rets[k] = r
        touch[k] = tt
        hits.append(h)
        labels[k] = 1 if h == _HIT_PT else (-1 if h == _HIT_SL else int(np.sign(r)))

    return pd.DataFrame(
        {"label": labels, "ret": rets, "t_touch": touch, "hit": hits, "bars": touch - events},
        index=events,
    )


def meta_bin(ret: Sequence[float], side: Sequence[int]) -> np.ndarray:
    """Meta-label: 1 if taking `side` (∈ {-1,0,1}) was profitable, else 0.

    This is the binary target a meta-model learns ("should I take the primary
    signal?"). A flat side (0) is never a bet → 0."""
    r = np.asarray(ret, dtype=float)
    s = np.asarray(side, dtype=float)
    return ((np.sign(r) == np.sign(s)) & (s != 0)).astype(int)


def side_pnl(ret: Sequence[float], side: Sequence[int]) -> np.ndarray:
    """Signed PnL of taking `side`: +ret for long, −ret for short, 0 for flat."""
    r = np.asarray(ret, dtype=float)
    s = np.asarray(side, dtype=float)
    return r * np.sign(s)
