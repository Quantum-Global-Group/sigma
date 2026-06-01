"""Richer option exits (PR-K) — manage_position external_exit priority +
the worker's pure, direction-aware _external_exit_reason."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sim.options.lifecycle import manage_position

# apps/worker on path (mirrors test_options_worker.py).
_worker = Path(__file__).parents[2] / "worker"
if str(_worker) not in sys.path:
    sys.path.insert(0, str(_worker))

import options_tick  # noqa: E402
from options_tick import _atr, _external_exit_reason  # noqa: E402


# ---------------------------------------------------------------------------
# manage_position honors external_exit at the right priority
# ---------------------------------------------------------------------------

def test_external_exit_closes_when_no_premium_exit():
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=101.0,
        T=0.20, sigma=0.3, hold_days=3, max_hold_days=21,
        external_exit="atr_stop",
    )
    assert a.action == "close" and a.outcome == "atr_stop"


def test_external_exit_yields_to_premium_stop_loss():
    # Deep loss → premium stop_loss must win over the external reason.
    a = manage_position(
        entry_price=8.0, qty=1, right="call", strike=100.0, spot=92.0,
        T=0.02, sigma=0.2, hold_days=3, max_hold_days=21,
        stop_loss_pct=0.5, external_exit="trend_reversal",
    )
    assert a.outcome == "stop_loss"


def test_external_exit_beats_time_stop():
    # Both external and time-stop would fire; external is higher priority.
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=104.0,
        T=0.20, sigma=0.3, hold_days=30, max_hold_days=21,
        external_exit="vol_regime",
    )
    assert a.outcome == "vol_regime"


def test_no_external_exit_marks():
    a = manage_position(
        entry_price=3.0, qty=1, right="call", strike=100.0, spot=104.0,
        T=0.20, sigma=0.3, hold_days=3, max_hold_days=21,
        external_exit=None,
    )
    assert a.action == "mark"


# ---------------------------------------------------------------------------
# _external_exit_reason (pure, direction-aware)
# ---------------------------------------------------------------------------

def _df(closes: list[float]) -> pd.DataFrame:
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c,
                         "volume": np.full(len(c), 1e6)})


def _ramp(a, b, n):
    return list(np.linspace(a, b, n))


def test_atr_helper_positive_on_moving_series():
    assert _atr(_df(_ramp(100, 120, 45)), 20) > 0


def test_atr_stop_fires_for_call_on_downtrend(monkeypatch):
    monkeypatch.setattr("config.settings.option_use_atr_trailing", True)
    # Up to a peak, then fall well below it.
    df = _df(_ramp(100, 120, 30) + _ramp(120, 107, 15))
    assert _external_exit_reason(df, "call") == "atr_stop"


def test_atr_stop_fires_for_put_on_uptrend(monkeypatch):
    monkeypatch.setattr("config.settings.option_use_atr_trailing", True)
    # Down to a trough, then rally well above it.
    df = _df(_ramp(120, 100, 30) + _ramp(100, 113, 15))
    assert _external_exit_reason(df, "put") == "atr_stop"


def test_atr_stop_does_not_fire_for_call_still_trending_up(monkeypatch):
    monkeypatch.setattr("config.settings.option_use_atr_trailing", True)
    df = _df(_ramp(100, 130, 45))            # steady uptrend — a call holds
    assert _external_exit_reason(df, "call") is None


def test_vol_regime_fires_on_spike(monkeypatch):
    monkeypatch.setattr("config.settings.option_use_vol_regime_exit", True)
    rng = np.random.default_rng(0)
    calm = list(100 + np.cumsum(rng.normal(0, 0.05, 22)))
    wild = list(calm[-1] + np.cumsum(rng.normal(0, 2.0, 22)))
    assert _external_exit_reason(_df(calm + wild), "call") == "vol_regime"


def test_trend_reversal_direction_aware(monkeypatch):
    monkeypatch.setattr("config.settings.option_use_trend_reversal", True)
    down = _df(_ramp(100, 120, 35) + _ramp(120, 110, 10))   # recent decline
    assert _external_exit_reason(down, "call") == "trend_reversal"   # bad for a call
    assert _external_exit_reason(down, "put") is None               # fine for a put


def test_returns_none_when_all_toggles_off():
    df = _df(_ramp(100, 120, 30) + _ramp(120, 107, 15))
    assert _external_exit_reason(df, "call") is None    # defaults are all off


def test_returns_none_on_insufficient_bars(monkeypatch):
    monkeypatch.setattr("config.settings.option_use_atr_trailing", True)
    assert _external_exit_reason(_df(_ramp(100, 110, 10)), "call") is None
