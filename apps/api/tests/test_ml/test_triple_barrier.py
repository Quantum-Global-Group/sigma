"""Tests for triple-barrier labeling (ml/triple_barrier.py)."""

from __future__ import annotations

import numpy as np

from ml.triple_barrier import meta_bin, side_pnl, triple_barrier


def _const_target(n, w=0.02):
    return np.full(n, w)


def test_monotonic_rise_hits_profit_take():
    close = np.linspace(100, 130, 31)        # strictly rising
    out = triple_barrier(close, _const_target(31), pt_mult=1.0, sl_mult=1.0, vbar_bars=10)
    # early events should touch the upper barrier first → label +1, hit 'pt'
    assert (out["label"].iloc[:20] == 1).all()
    assert (out["hit"].iloc[:20] == "pt").all()
    assert (out["ret"].iloc[:20] > 0).all()


def test_monotonic_fall_hits_stop_loss():
    close = np.linspace(130, 100, 31)        # strictly falling
    out = triple_barrier(close, _const_target(31), pt_mult=1.0, sl_mult=1.0, vbar_bars=10)
    assert (out["label"].iloc[:20] == -1).all()
    assert (out["hit"].iloc[:20] == "sl").all()
    assert (out["ret"].iloc[:20] < 0).all()


def test_flat_series_hits_vertical_barrier_flat():
    close = np.full(20, 100.0)
    out = triple_barrier(close, _const_target(20), vbar_bars=5)
    assert (out["hit"] == "vbar").all()
    assert (out["label"] == 0).all()
    assert (out["ret"] == 0).all()


def test_bars_held_and_touch_positions():
    close = np.full(20, 100.0)
    out = triple_barrier(close, _const_target(20), vbar_bars=5)
    # vertical barrier 5 bars out (clamped near the end)
    assert out["bars"].iloc[0] == 5
    assert out["t_touch"].iloc[0] == 5


def test_profit_before_stop_when_up_first():
    # up to 103 (pt at +2% = 102) then crash — pt must register first
    close = np.array([100, 101, 103, 90, 90, 90], dtype=float)
    out = triple_barrier(close, _const_target(6, 0.02), pt_mult=1.0, sl_mult=1.0, vbar_bars=5,
                         t_events=[0])
    assert out["hit"].iloc[0] == "pt"
    assert out["t_touch"].iloc[0] == 2          # touched +2% at bar 2, before the crash
    assert out["label"].iloc[0] == 1


def test_no_lookahead_past_first_touch():
    """Changing any bar *after* the first touch must not change the label/return."""
    base = np.array([100, 101, 103, 99, 99, 99], dtype=float)
    out1 = triple_barrier(base, _const_target(6, 0.02), vbar_bars=5, t_events=[0])
    mutated = base.copy()
    mutated[3:] = 50.0                            # crater everything after the touch (bar 2)
    out2 = triple_barrier(mutated, _const_target(6, 0.02), vbar_bars=5, t_events=[0])
    assert out1["t_touch"].iloc[0] == 2
    assert out1["label"].iloc[0] == out2["label"].iloc[0]
    assert out1["ret"].iloc[0] == out2["ret"].iloc[0]


def test_vertical_barrier_clamps_at_series_end():
    close = np.linspace(100, 101, 4)             # tiny drift, won't hit 2% barriers
    out = triple_barrier(close, _const_target(4, 0.02), vbar_bars=10)
    # last event can't look 10 bars ahead → clamps to the final bar
    assert out["t_touch"].iloc[-1] == 3


def test_meta_bin_and_side_pnl():
    ret = np.array([0.01, -0.02, 0.03, 0.0])
    side = np.array([1, 1, -1, 1])
    # long+up=win, long+down=loss, short+up=loss, flat-return long=loss
    assert meta_bin(ret, side).tolist() == [1, 0, 0, 0]
    assert np.allclose(side_pnl(ret, side), [0.01, -0.02, -0.03, 0.0])


def test_meta_bin_flat_side_never_bets():
    assert meta_bin([0.05], [0]).tolist() == [0]
