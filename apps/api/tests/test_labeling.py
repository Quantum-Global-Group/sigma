"""Outcome-labeling tests (PR-D) — pure helpers + orchestration with injected I/O."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ml.labeling import classify_outcome, compute_realized_return, label_outcomes


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def test_compute_realized_return():
    assert compute_realized_return(100.0, 105.0) == pytest.approx(0.05)
    assert compute_realized_return(100.0, 95.0) == pytest.approx(-0.05)
    assert compute_realized_return(0.0, 50.0) == 0.0   # guards div-by-zero


@pytest.mark.parametrize("signal,rr,expected", [
    ("BUY", 0.05, "win"),     # bought, went up
    ("BUY", -0.05, "loss"),   # bought, went down
    ("SELL", -0.05, "win"),   # sold, went down
    ("SELL", 0.05, "loss"),   # sold, went up
    ("HOLD", 0.05, "flat"),   # HOLD never win/loss
    ("BUY", 0.0005, "flat"),  # sub-threshold move
    ("SELL", -0.0001, "flat"),
])
def test_classify_outcome(signal, rr, expected):
    assert classify_outcome(signal, rr, flat_threshold=0.001) == expected


# ---------------------------------------------------------------------------
# label_outcomes orchestration (injected fetch + patched signal query)
# ---------------------------------------------------------------------------

def _sig(ticker, signal, ts=None):
    return SimpleNamespace(
        ticker=ticker, timeframe="daily", signal=signal,
        created_at=ts or datetime(2026, 1, 1, tzinfo=timezone.utc),
        realized_return=None, outcome=None, labeled_at=None,
    )


@pytest.mark.asyncio
async def test_label_outcomes_labels_with_forward_prices(monkeypatch):
    signals = [_sig("AAPL", "BUY"), _sig("MSFT", "SELL"), _sig("NVDA", "HOLD")]

    async def fake_unlabeled(session, asset_class, limit):
        return signals

    # AAPL +5%, MSFT -3%, NVDA +0.05% (flat)
    prices = {
        "AAPL": (100.0, 105.0),
        "MSFT": (100.0, 97.0),
        "NVDA": (100.0, 100.05),
    }

    async def fake_fetch(session, asset_class, ticker, timeframe, ts, horizon):
        return prices[ticker]

    monkeypatch.setattr("ml.labeling._unlabeled_signals", fake_unlabeled)

    n = await label_outcomes(MagicMock(), "equity", horizon_bars=5,
                             flat_threshold=0.001, fetch_prices=fake_fetch)
    assert n == 3
    assert signals[0].outcome == "win" and signals[0].realized_return == pytest.approx(0.05)
    assert signals[1].outcome == "win" and signals[1].realized_return == pytest.approx(-0.03)
    assert signals[2].outcome == "flat"
    assert all(s.labeled_at is not None for s in signals)


@pytest.mark.asyncio
async def test_label_outcomes_skips_when_forward_window_unfilled(monkeypatch):
    signals = [_sig("AAPL", "BUY")]

    async def fake_unlabeled(session, asset_class, limit):
        return signals

    async def fake_fetch(session, *a):
        return None  # forward bars not available yet

    monkeypatch.setattr("ml.labeling._unlabeled_signals", fake_unlabeled)
    n = await label_outcomes(MagicMock(), "equity", fetch_prices=fake_fetch)
    assert n == 0
    assert signals[0].labeled_at is None  # left for a later run
