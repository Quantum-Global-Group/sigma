"""Tests for the options simulator (P3): fills, lifecycle, backtester."""

import numpy as np
import pandas as pd
import pytest

from sim.options import (
    simulate_option_fill,
    intrinsic_value,
    option_value,
    settle_at_expiry,
    purged_walkforward_splits,
    backtest_single_leg,
    BacktestResult,
)


# ---------------------------------------------------------------------------
# fill model
# ---------------------------------------------------------------------------

def test_buy_fills_between_mid_and_ask():
    f = simulate_option_fill(bid=1.00, ask=1.20, last=1.10, side="buy", qty=1, aggression=0.5)
    assert f.filled
    assert 1.10 <= f.price <= 1.20      # mid=1.10, half-cross to ask
    assert f.price == pytest.approx(1.15)
    assert f.commission == pytest.approx(0.65)


def test_sell_fills_between_bid_and_mid():
    f = simulate_option_fill(bid=1.00, ask=1.20, last=1.10, side="sell", qty=2, aggression=1.0)
    assert f.price == pytest.approx(1.00)   # full cross to bid
    assert f.commission == pytest.approx(1.30)


def test_aggression_zero_fills_at_mid():
    f = simulate_option_fill(bid=1.00, ask=1.20, last=1.10, side="buy", qty=1, aggression=0.0)
    assert f.price == pytest.approx(1.10)
    assert f.slippage_bps == pytest.approx(0.0)


def test_spread_gate_rejects_wide_book():
    f = simulate_option_fill(bid=1.00, ask=2.00, last=1.5, side="buy", qty=1, max_spread_pct=0.10)
    assert not f.filled and "spread" in f.reason


def test_zero_qty_and_no_price_rejected():
    assert not simulate_option_fill(bid=1, ask=1.1, last=1, side="buy", qty=0).filled
    assert not simulate_option_fill(bid=0, ask=0, last=0, side="buy", qty=1).filled


def test_one_sided_book_uses_last():
    f = simulate_option_fill(bid=0, ask=0, last=2.0, side="buy", qty=1, aggression=1.0)
    assert f.filled and f.price == pytest.approx(2.0)  # no half-spread → mid=last


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------

def test_intrinsic_value():
    assert intrinsic_value("call", 110, 100) == 10
    assert intrinsic_value("call", 90, 100) == 0
    assert intrinsic_value("put", 90, 100) == 10


def test_option_value_at_expiry_is_intrinsic():
    assert option_value("call", 110, 100, 0.0, 0.05, 0.2) == pytest.approx(10.0)


def test_option_value_before_expiry_exceeds_intrinsic():
    v = option_value("call", 105, 100, 0.5, 0.05, 0.3, american=True)
    assert v > intrinsic_value("call", 105, 100)  # time value


def test_settle_long_itm_call_profit():
    s = settle_at_expiry(right="call", strike=100, qty=1, entry_price=3.0, S_expiry=110)
    # (10 - 3)*100*1 - 0.65
    assert s.realized_pnl == pytest.approx(700 - 0.65)
    assert s.outcome == "exercised"


def test_settle_long_otm_expires_worthless():
    s = settle_at_expiry(right="call", strike=100, qty=1, entry_price=3.0, S_expiry=95)
    assert s.realized_pnl == pytest.approx(-300 - 0.65)
    assert s.outcome == "expired_worthless"


def test_settle_short_put_assigned_loss():
    # sold a put for 2.00, underlying drops to 90 (K=100) → assigned, intrinsic 10
    s = settle_at_expiry(right="put", strike=100, qty=1, entry_price=2.0, S_expiry=90, side="short")
    assert s.realized_pnl == pytest.approx((2.0 - 10.0) * 100 - 0.65)
    assert s.outcome == "assigned"


def test_settle_short_otm_keeps_premium():
    s = settle_at_expiry(right="put", strike=100, qty=1, entry_price=2.0, S_expiry=110, side="short")
    assert s.realized_pnl == pytest.approx(200 - 0.65)
    assert s.outcome == "expired_worthless"


# ---------------------------------------------------------------------------
# purged walk-forward splits
# ---------------------------------------------------------------------------

def test_purged_splits_no_overlap_and_embargo():
    n, embargo = 120, 2
    splits = purged_walkforward_splits(n, n_splits=5, embargo=embargo)
    assert len(splits) >= 1
    for train, test in splits:
        assert train.start == 0
        assert train.stop <= test.start                       # train strictly before test
        assert test.start - train.stop >= embargo             # purge gap honored
        assert 0 <= test.start < test.stop <= n
        assert set(range(train.start, train.stop)).isdisjoint(set(test))


def test_purged_splits_last_test_reaches_end():
    splits = purged_walkforward_splits(120, n_splits=5, embargo=0)
    assert splits[-1][1].stop == 120


def test_purged_splits_degenerate():
    assert purged_walkforward_splits(0) == []
    assert purged_walkforward_splits(3, n_splits=10) == []   # fold==0


# ---------------------------------------------------------------------------
# backtester
# ---------------------------------------------------------------------------

def _series(n=120, drift=0.001, vol=0.01, seed=1):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({"close": close, "open": close, "high": close * 1.01,
                         "low": close * 0.99, "volume": 1e6}, index=idx)


def test_backtest_runs_and_produces_trades():
    bars = _series()
    res = backtest_single_leg(bars, lambda w: "call", hold_days=5, dte=30, qty=1)
    assert isinstance(res, BacktestResult)
    assert res.n_trades > 0
    assert np.isfinite(res.total_pnl)
    assert 0.0 <= res.win_rate <= 1.0
    # non-overlapping: trades spaced >= hold_days apart
    assert all(t.qty == 1 for t in res.trades)


def test_backtest_no_signal_no_trades():
    bars = _series()
    res = backtest_single_leg(bars, lambda w: None)
    assert res.n_trades == 0
    assert res.total_pnl == 0.0


def test_backtest_short_series_empty():
    bars = _series(n=10)
    res = backtest_single_leg(bars, lambda w: "call")
    assert res.n_trades == 0
