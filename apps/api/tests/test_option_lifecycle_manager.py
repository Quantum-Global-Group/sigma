"""Option lifecycle manager tests (PR-F) — settle / time_stop / mark selection."""

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
    assert a.action == "settle" and a.closes
    assert a.outcome == "exercised"
    # (10 - 2) * 100 * 1 - 0.65
    assert a.realized_pnl == pytest.approx(800.0 - 0.65)
    assert a.unrealized_pnl == 0.0


def test_settle_otm_long_put_expires_worthless():
    a = manage_position(
        entry_price=1.5, qty=2, right="put", strike=100.0, spot=120.0,
        T=0.0, sigma=0.3, hold_days=10, max_hold_days=21,
    )
    assert a.action == "settle" and a.outcome == "expired_worthless"
    # (0 - 1.5) * 100 * 2 - commission
    assert a.realized_pnl < 0


# --------------------------------------------------------------------------
# time stop (hold_days >= max_hold_days)
# --------------------------------------------------------------------------

def test_time_stop_closes_at_theoretical_value():
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=105.0,
        T=0.10, sigma=0.3, hold_days=21, max_hold_days=21,
    )
    assert a.action == "time_stop" and a.closes
    assert a.outcome == "time_stop"
    assert a.current_px > 0           # priced, not intrinsic-only
    assert a.unrealized_pnl == 0.0    # closing → realized, not unrealized


# --------------------------------------------------------------------------
# mark (still open)
# --------------------------------------------------------------------------

def test_mark_updates_unrealized_and_stays_open():
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=108.0,
        T=0.20, sigma=0.3, hold_days=5, max_hold_days=21,
    )
    assert a.action == "mark" and not a.closes
    assert a.outcome == "held"
    assert a.current_px > 0
    # ITM and up from entry → positive unrealized
    assert a.unrealized_pnl == pytest.approx((a.current_px - 3.0) * 100 * 1)
    assert a.realized_pnl == 0.0


def test_mark_loss_when_value_below_entry():
    a = manage_position(
        entry_price=8.0, qty=1, right="call", strike=100.0, spot=96.0,
        T=0.05, sigma=0.2, hold_days=3, max_hold_days=21,
    )
    assert a.action == "mark"
    assert a.unrealized_pnl < 0       # paid 8.00, now worth less
