"""Test the ExitState <-> razorBill state-dict bridge in worker.tick."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

APPS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APPS_DIR))


def test_to_dict_with_no_row_uses_seed():
    from worker.tick import _exit_state_to_dict

    state = _exit_state_to_dict(None, high_water_seed=100.0)
    assert state == {
        "took_partial": False,
        "breakeven_px": None,
        "tight_trailing": None,
        "high_water_px": 100.0,
    }


def test_to_dict_translates_orm_columns():
    from worker.tick import _exit_state_to_dict

    es = MagicMock()
    es.partial_tp_done = True
    es.breakeven_px = 100.5
    es.trailing_stop_px = 98.7
    es.high_water_px = 102.3

    assert _exit_state_to_dict(es) == {
        "took_partial": True,
        "breakeven_px": 100.5,
        "tight_trailing": 98.7,
        "high_water_px": 102.3,
    }


def test_apply_state_writes_back_translation():
    from worker.tick import _apply_state_to_es

    es = MagicMock()
    es.partial_tp_done = False
    es.breakeven_px = None
    es.trailing_stop_px = None
    es.high_water_px = None
    es.last_evaluated_at = None

    _apply_state_to_es(es, {
        "took_partial": True,
        "breakeven_px": 105.0,
        "tight_trailing": 103.0,
        "high_water_px": 107.5,
    })

    assert es.partial_tp_done is True
    assert es.breakeven_px == 105.0
    assert es.trailing_stop_px == 103.0
    assert es.high_water_px == 107.5
    assert isinstance(es.last_evaluated_at, datetime)
    assert es.last_evaluated_at.tzinfo == timezone.utc


def test_apply_state_handles_none_values():
    from worker.tick import _apply_state_to_es

    es = MagicMock()
    _apply_state_to_es(es, {"took_partial": False, "breakeven_px": None, "tight_trailing": None, "high_water_px": None})

    assert es.partial_tp_done is False
    assert es.breakeven_px is None
    assert es.trailing_stop_px is None
    assert es.high_water_px is None
