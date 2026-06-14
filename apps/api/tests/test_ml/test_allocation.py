"""Tests for ml/allocation.py — the trend-filtered allocation strategy core."""

import sys
from pathlib import Path

_api = Path(__file__).parents[2]
sys.path.insert(0, str(_api))

import numpy as np
import pandas as pd
import pytest

from ml.allocation import (
    RebalanceOrder,
    in_trend,
    parse_weights,
    rebalance_orders,
    target_weights,
)


# ---------------------------------------------------------------------------
# parse_weights
# ---------------------------------------------------------------------------

def test_parse_weights_normalizes():
    w = parse_weights("SPY:0.30,TLT:0.15,GLD:0.05")
    assert w["SPY"] == pytest.approx(0.30 / 0.50)
    assert sum(w.values()) == pytest.approx(1.0)


def test_parse_weights_ignores_junk_and_nonpositive():
    w = parse_weights("SPY:0.5, BAD, TLT:0.5, NEG:-1")
    assert set(w) == {"SPY", "TLT"} and sum(w.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# in_trend
# ---------------------------------------------------------------------------

def _daily(prices):
    idx = pd.date_range("2020-01-01", periods=len(prices), freq="D")
    return pd.Series(prices, index=idx)


def test_in_trend_true_when_rising():
    s = _daily(np.linspace(100, 200, 400))   # > 1yr of daily, steadily up
    assert in_trend(s, 10) is True


def test_in_trend_false_when_falling():
    s = _daily(np.linspace(200, 100, 400))   # steadily down
    assert in_trend(s, 10) is False


def test_in_trend_holds_when_insufficient_history():
    s = _daily(np.linspace(100, 90, 20))     # < 11 months → don't gate
    assert in_trend(s, 10) is True


# ---------------------------------------------------------------------------
# target_weights
# ---------------------------------------------------------------------------

def test_target_weights_zeroes_downtrend_sleeves():
    prices = {"SPY": _daily(np.linspace(100, 200, 400)),   # up → keep
              "TLT": _daily(np.linspace(200, 100, 400))}   # down → cash
    base = {"SPY": 0.6, "TLT": 0.4}
    t = target_weights(prices, base, 10)
    assert t["SPY"] == pytest.approx(0.6)
    assert t["TLT"] == 0.0
    assert sum(t.values()) < 1.0           # remainder is cash (de-risked)


def test_target_weights_missing_price_goes_cash():
    t = target_weights({"SPY": _daily(np.linspace(100, 200, 400))},
                       {"SPY": 0.5, "GLD": 0.5}, 10)
    assert t["SPY"] == pytest.approx(0.5) and t["GLD"] == 0.0


# ---------------------------------------------------------------------------
# rebalance_orders
# ---------------------------------------------------------------------------

def test_rebalance_from_cash_buys_to_target():
    orders = rebalance_orders({"SPY": 0.5}, equity=10_000, current_qty={},
                              last_price={"SPY": 100.0})
    assert len(orders) == 1
    o = orders[0]
    assert o.symbol == "SPY" and o.side == "buy"
    assert o.notional == pytest.approx(5000.0) and o.qty == pytest.approx(50.0)


def test_rebalance_sells_out_of_trend_holding():
    # held SPY but target is 0 → sell it all
    orders = rebalance_orders({"SPY": 0.0}, equity=10_000,
                              current_qty={"SPY": 50.0}, last_price={"SPY": 100.0})
    assert orders == [RebalanceOrder("SPY", "sell", 50.0, 5000.0)]


def test_rebalance_skips_dust():
    # already at target within $50 → no order
    orders = rebalance_orders({"SPY": 0.5}, equity=10_000,
                              current_qty={"SPY": 49.7}, last_price={"SPY": 100.0},
                              min_trade_usd=50.0)
    assert orders == []


def test_rebalance_trims_overweight():
    # holding $8k of SPY, target $5k → sell $3k
    orders = rebalance_orders({"SPY": 0.5}, equity=10_000,
                              current_qty={"SPY": 80.0}, last_price={"SPY": 100.0})
    assert orders[0].side == "sell" and orders[0].notional == pytest.approx(3000.0)


def test_rebalance_zero_price_skipped():
    orders = rebalance_orders({"SPY": 0.5}, equity=10_000, current_qty={},
                              last_price={"SPY": 0.0})
    assert orders == []


def test_rebalance_full_book_buys_each_in_trend_sleeve():
    targets = {"SPY": 0.5, "TLT": 0.3, "GLD": 0.0}   # GLD out of trend
    orders = rebalance_orders(targets, equity=100_000, current_qty={},
                              last_price={"SPY": 100, "TLT": 50, "GLD": 20})
    by = {o.symbol: o for o in orders}
    assert by["SPY"].notional == pytest.approx(50_000)
    assert by["TLT"].notional == pytest.approx(30_000)
    assert "GLD" not in by                            # 0 target, nothing held
