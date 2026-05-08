"""Unit tests for the rebuy cooldown helper in worker.tick."""

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

WORKER_PATH = Path(__file__).resolve().parents[3] / "worker"
sys.path.insert(0, str(WORKER_PATH.parent))


def test_in_cooldown_true_when_recent_sell(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "rebuy_cooldown_min", 15)

    from worker.tick import _in_cooldown

    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert _in_cooldown("BTC-USD", {"BTC-USD": recent}) is True


def test_in_cooldown_false_when_outside_window(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "rebuy_cooldown_min", 15)

    from worker.tick import _in_cooldown

    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    assert _in_cooldown("BTC-USD", {"BTC-USD": old}) is False


def test_in_cooldown_false_when_no_recent_sell():
    from worker.tick import _in_cooldown

    assert _in_cooldown("BTC-USD", {}) is False


def test_in_cooldown_handles_naive_datetime(monkeypatch):
    """If a naive datetime sneaks in (sqlite, certain drivers), assume UTC."""
    from config import settings as cfg
    monkeypatch.setattr(cfg, "rebuy_cooldown_min", 15)

    from worker.tick import _in_cooldown

    naive = datetime.utcnow() - timedelta(minutes=5)  # naive
    assert _in_cooldown("BTC-USD", {"BTC-USD": naive}) is True
