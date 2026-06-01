"""Option lifecycle manager tests (PR-F + PR-I).

manage_position returns action == "close" (with `outcome` saying why) or "mark".
Priority: settle → stop_loss → take_profit → trailing_stop → time_stop → mark.
"""

import pytest

from sim.options.lifecycle import manage_position


# --------------------------------------------------------------------------
# settle at expiry (T <= 0)
# --------------------------------------------------------------------------

def test_settle_itm_long_call_books_realized():
    # Long call, entry $2.00, expires with spot 110 vs strike 100 → intrinsic 10
    a = manage_position(
        entry_price=2.0, qty=1, right="call", strike=100.0, spot=110.0,
        T=0.0, sigma=0.3, hold_days=30, max_hold_days=21, commission_per_contract=0.65,
    )
    assert a.action == "close" and a.closes
    assert a.outcome == "exercised"
    assert a.realized_pnl == pytest.approx(800.0 - 0.65)   # (10-2)*100 - 0.65
    assert a.unrealized_pnl == 0.0


def test_settle_otm_long_put_expires_worthless():
    a = manage_position(
        entry_price=1.5, qty=2, right="put", strike=100.0, spot=120.0,
        T=0.0, sigma=0.3, hold_days=10, max_hold_days=21,
    )
    assert a.action == "close" and a.outcome == "expired_worthless"
    assert a.realized_pnl < 0


# --------------------------------------------------------------------------
# time stop (hold_days >= max_hold_days)
# --------------------------------------------------------------------------

def test_time_stop_closes_at_theoretical_value():
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=105.0,
        T=0.10, sigma=0.3, hold_days=21, max_hold_days=21,
    )
    assert a.action == "close" and a.outcome == "time_stop"
    assert a.current_px > 0
    assert a.unrealized_pnl == 0.0


# --------------------------------------------------------------------------
# price-based exits (PR-I)
# --------------------------------------------------------------------------

def test_stop_loss_fires_below_floor():
    # Deep OTM near expiry → mark well under entry*(1-0.5). entry 8.00.
    a = manage_position(
        entry_price=8.0, qty=1, right="call", strike=100.0, spot=92.0,
        T=0.02, sigma=0.2, hold_days=3, max_hold_days=21,
        stop_loss_pct=0.5,
    )
    assert a.action == "close" and a.outcome == "stop_loss"
    assert a.current_px <= 8.0 * 0.5
    assert a.realized_pnl < 0


def test_take_profit_fires_above_target():
    # Deep ITM → mark well above entry*2. entry 2.00, spot 130 vs strike 100.
    a = manage_position(
        entry_price=2.0, qty=1, right="call", strike=100.0, spot=130.0,
        T=0.20, sigma=0.3, hold_days=3, max_hold_days=21,
        take_profit_pct=1.0,
    )
    assert a.action == "close" and a.outcome == "take_profit"
    assert a.current_px >= 2.0 * 2.0
    assert a.realized_pnl > 0


def test_trailing_arms_after_gain_then_fires_on_pullback():
    # High-water 20.00 (entry 2.00 → past the 30% activation gate). The current
    # mark (~$8 ITM call) is well under 20*(1-0.3)=14 → trailing fires.
    a = manage_position(
        entry_price=2.0, qty=1, right="call", strike=100.0, spot=105.0,
        T=0.20, sigma=0.3, hold_days=3, max_hold_days=21,
        high_water_value=20.0, trailing_pct=0.3, trailing_activate_pct=0.3,
    )
    assert a.action == "close" and a.outcome == "trailing_stop"
    assert a.current_px < 14.0


def test_trailing_does_not_fire_before_activation():
    # Never ran up enough (high-water ~= entry) → trailing inactive → marks.
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=101.0,
        T=0.20, sigma=0.3, hold_days=3, max_hold_days=21,
        high_water_value=3.0, trailing_pct=0.3, trailing_activate_pct=0.3,
    )
    assert a.action == "mark"


def test_stop_loss_takes_priority_over_time_stop():
    # Both the stop and the time-stop would trigger; stop_loss wins.
    a = manage_position(
        entry_price=8.0, qty=1, right="call", strike=100.0, spot=92.0,
        T=0.02, sigma=0.2, hold_days=30, max_hold_days=21,
        stop_loss_pct=0.5,
    )
    assert a.outcome == "stop_loss"


# --------------------------------------------------------------------------
# mark (still open) — high-water advances
# --------------------------------------------------------------------------

def test_mark_updates_unrealized_and_tracks_high_water():
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=108.0,
        T=0.20, sigma=0.3, hold_days=5, max_hold_days=21,
        high_water_value=3.0,
    )
    assert a.action == "mark" and not a.closes
    assert a.outcome == "held"
    assert a.unrealized_pnl == pytest.approx((a.current_px - 3.0) * 100 * 1)
    assert a.high_water_value >= a.current_px        # high-water ≥ current value
    assert a.high_water_value >= 3.0                 # never below the prior high-water


def test_mark_loss_when_value_below_entry():
    a = manage_position(
        entry_price=8.0, qty=1, right="call", strike=100.0, spot=96.0,
        T=0.05, sigma=0.2, hold_days=3, max_hold_days=21,
    )
    assert a.action == "mark"
    assert a.unrealized_pnl < 0
