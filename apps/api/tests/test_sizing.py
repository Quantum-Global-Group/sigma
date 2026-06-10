"""Confidence-based Kelly sizing (item #4): meta P(win) → bet fraction.

With symmetric triple barriers the payoff ratio ≈ 1, so kelly ≈ 2·P(win) − 1:
higher meta confidence ⇒ larger bet; P(win) ≤ 0.5 ⇒ no bet.
"""

from __future__ import annotations

from risk.sizing import PositionSizer


def test_kelly_scales_with_win_rate():
    s = PositionSizer(equity=10_000)
    lo = s.kelly_optimal(price=100, signal=1.0, win_rate=0.55, avg_win=0.02, avg_loss=0.02)
    hi = s.kelly_optimal(price=100, signal=1.0, win_rate=0.65, avg_win=0.02, avg_loss=0.02)
    assert hi.notional > lo.notional > 0.0


def test_kelly_no_bet_at_coinflip_equal_payoff():
    s = PositionSizer(equity=10_000)
    flat = s.kelly_optimal(price=100, signal=1.0, win_rate=0.50, avg_win=0.02, avg_loss=0.02)
    assert flat.qty == 0.0 and flat.notional == 0.0


def test_kelly_signal_strength_scales_bet():
    s = PositionSizer(equity=10_000)
    weak = s.kelly_optimal(price=100, signal=0.3, win_rate=0.65, avg_win=0.02, avg_loss=0.02)
    strong = s.kelly_optimal(price=100, signal=1.0, win_rate=0.65, avg_win=0.02, avg_loss=0.02)
    assert strong.notional > weak.notional > 0.0
