"""Mark-to-market helper tests (PR-F)."""

import pytest

from risk.pnl import position_value, unrealized


def test_unrealized_long_gain():
    assert unrealized(entry_px=100.0, qty=10, current_px=105.0) == pytest.approx(50.0)


def test_unrealized_long_loss():
    assert unrealized(entry_px=100.0, qty=10, current_px=95.0) == pytest.approx(-50.0)


def test_unrealized_with_multiplier():
    # An option: 2 contracts, $1.00 → $1.50, x100 multiplier = +$100
    assert unrealized(entry_px=1.0, qty=2, current_px=1.5, multiplier=100) == pytest.approx(100.0)


def test_position_value():
    assert position_value(qty=10, current_px=105.0) == pytest.approx(1050.0)
    assert position_value(qty=2, current_px=1.5, multiplier=100) == pytest.approx(300.0)
