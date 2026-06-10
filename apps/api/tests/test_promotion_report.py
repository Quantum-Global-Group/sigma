"""Tests for promotion report builder."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ml.promotion_report import build_promotion_report


def test_build_promotion_report_not_found():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    assert asyncio.run(build_promotion_report(session, uuid.uuid4())) is None


def test_build_promotion_report_structure():
    promo = MagicMock()
    promo.id = uuid.uuid4()
    promo.asset_class = "equity"
    promo.model_type = "ensemble"
    promo.from_version = "v1.0"
    promo.to_version = "cand-20260101"
    promo.status = "pending"
    promo.proposed_at = datetime.now(timezone.utc)
    promo.decided_at = None
    promo.decided_by = None
    promo.rationale = {"improvement": 0.03}

    cand = MagicMock()
    cand.model_version = "cand-20260101"
    cand.eval_date = datetime.now(timezone.utc)
    cand.n_samples = 100
    cand.directional_accuracy = 0.62
    cand.signal_accuracy = 0.60
    cand.mean_abs_error = None
    cand.backtest_sharpe = None
    cand.backtest_win_rate = None
    cand.metrics = {}
    cand.notes = None

    inc = MagicMock()
    inc.model_version = "v1.0"
    inc.eval_date = datetime.now(timezone.utc)
    inc.n_samples = 200
    inc.directional_accuracy = 0.58
    inc.signal_accuracy = 0.57
    inc.mean_abs_error = None
    inc.backtest_sharpe = None
    inc.backtest_win_rate = None
    inc.metrics = {}
    inc.notes = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=promo)

    call_count = 0

    async def fake_execute(q):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = cand if call_count == 1 else inc
        return result

    session.execute = fake_execute

    report = asyncio.run(build_promotion_report(session, promo.id))
    assert report is not None
    assert report["promotion"]["to_version"] == "cand-20260101"
    assert report["candidate"]["directional_accuracy"] == 0.62
    assert report["comparison"]["directional_accuracy_delta"] == pytest.approx(0.04)
    assert report["recommendation"] == "candidate_leads"
    assert "summary" in report
