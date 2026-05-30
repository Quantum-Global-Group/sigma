"""Tests for the options risk layer (P5): greeks, kill-switch, audit, sizing."""

import pytest

from risk.greeks import (
    GreekLimits, aggregate_greeks, check_greek_limits, delta_hedge,
)
from risk.kill_switch import KillSwitch, HaltThresholds, evaluate_halt
from risk.audit_log import AuditLog, AuditRecord
from risk.option_sizing import option_position_size


# ---------------------------------------------------------------------------
# portfolio greeks
# ---------------------------------------------------------------------------

def test_aggregate_greeks_signed_and_scaled():
    positions = [
        {"greeks": {"delta": 0.5, "gamma": 0.02, "theta": -0.03, "vega": 0.10}, "qty": 2, "multiplier": 100},
        {"greeks": {"delta": -0.4, "gamma": 0.01, "theta": -0.01, "vega": 0.05}, "qty": -1, "multiplier": 100},
    ]
    net = aggregate_greeks(positions)
    # delta: 0.5*2*100 + (-0.4)*(-1)*100 = 100 + 40 = 140
    assert net.delta == pytest.approx(140.0)
    assert net.as_dict()["delta"] == pytest.approx(140.0)


def test_check_greek_limits_breach_and_ok():
    net = aggregate_greeks([{"greeks": {"delta": 1.0}, "qty": 5, "multiplier": 100}])  # 500
    ok, breaches = check_greek_limits(net, GreekLimits(max_abs_net_delta=300))
    assert not ok and breaches
    ok2, _ = check_greek_limits(net, GreekLimits(max_abs_net_delta=0))  # 0 disables
    assert ok2


def test_delta_hedge_sells_to_flatten_long_delta():
    h = delta_hedge(140.0, tolerance=1.0)
    assert h.side == "sell" and h.shares == pytest.approx(-140.0)
    flat = delta_hedge(0.5, tolerance=1.0)
    assert flat.side == "none"


# ---------------------------------------------------------------------------
# kill switch
# ---------------------------------------------------------------------------

def test_kill_switch_trip_and_reset():
    ks = KillSwitch()
    assert ks.allow_new_entries()
    ks.trip("data anomaly")
    assert ks.tripped and not ks.allow_new_entries()
    assert ks.reason == "data anomaly"
    ks.reset()
    assert ks.allow_new_entries() and not ks.tripped
    assert len(ks.history) == 2


def test_evaluate_halt_portfolio_loss():
    should, reasons = evaluate_halt(
        equity=8500, starting_equity=10000, daily_pnl=-100, peak_equity=10000,
        thresholds=HaltThresholds(max_portfolio_loss_pct=0.10),
    )
    assert should and any("portfolio loss" in r for r in reasons)


def test_evaluate_halt_drawdown_and_data():
    should, reasons = evaluate_halt(
        equity=7900, starting_equity=10000, daily_pnl=0, peak_equity=10000,
        thresholds=HaltThresholds(max_portfolio_loss_pct=0.5, max_daily_loss_pct=0.5, max_drawdown_pct=0.20),
        data_ok=False, greek_breaches=["net vega 5000 exceeds 4000"],
    )
    assert should
    assert any("drawdown" in r for r in reasons)
    assert "data quality failure" in reasons
    assert any("vega" in r for r in reasons)


def test_evaluate_halt_clean_state():
    should, reasons = evaluate_halt(
        equity=10100, starting_equity=10000, daily_pnl=100, peak_equity=10100,
        thresholds=HaltThresholds(),
    )
    assert not should and reasons == []


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------

def test_audit_record_gates_and_finalize():
    log = AuditLog()
    rec = log.new("US.AAPL260116C00250000", strategy="long_call")
    rec.gate("data", True).gate("signal", True).gate("risk", False, ["net delta exceeds cap"])
    assert not rec.all_gates_passed
    rec.finalize("skipped", client_order_id="x")
    assert rec.decision == "skipped"
    d = rec.to_dict()
    assert d["strategy"] == "long_call" and len(d["gates"]) == 3
    assert log.to_list()[0]["symbol"].startswith("US.AAPL")


def test_audit_log_placed_filter():
    log = AuditLog()
    log.new("A").finalize("placed")
    log.new("B").finalize("skipped")
    assert len(log.placed()) == 1


# ---------------------------------------------------------------------------
# option position sizing
# ---------------------------------------------------------------------------

def test_sizing_by_risk_budget():
    # equity 10k, 2% risk = $200 budget; max loss $50/contract → 4 contracts
    s = option_position_size(equity=10_000, max_loss_per_contract=50, risk_per_trade=0.02)
    assert s.contracts == 4
    assert s.binding == "risk_budget"
    assert s.risk_budget == pytest.approx(200.0)


def test_sizing_capped_by_max_contracts():
    s = option_position_size(equity=1_000_000, max_loss_per_contract=10, risk_per_trade=0.02, max_contracts=50)
    assert s.contracts == 50 and s.binding == "max_contracts"


def test_sizing_below_one_contract():
    s = option_position_size(equity=1_000, max_loss_per_contract=500, risk_per_trade=0.02)
    assert s.contracts == 0 and s.binding == "below-one-contract"


def test_sizing_drawdown_and_liquidity_shrink():
    full = option_position_size(equity=10_000, max_loss_per_contract=50, risk_per_trade=0.10)
    shrunk = option_position_size(
        equity=10_000, max_loss_per_contract=50, risk_per_trade=0.10,
        drawdown_factor=0.5, liquidity_factor=0.5,
    )
    assert shrunk.contracts < full.contracts


def test_sizing_kelly_overrides_when_higher():
    # kelly 5% (capped 25%) > risk_per_trade 2% → larger budget
    s = option_position_size(
        equity=10_000, max_loss_per_contract=50, kelly_fraction=0.05, risk_per_trade=0.02,
    )
    assert s.risk_budget == pytest.approx(500.0)  # 5% of 10k
    assert s.contracts == 10


def test_sizing_zero_equity():
    s = option_position_size(equity=0, max_loss_per_contract=50)
    assert s.contracts == 0 and s.binding == "no-budget"
