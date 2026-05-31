"""Worker scheduler tests (PR-E) — job wiring without a live APScheduler clock."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# apps/worker on path (mirrors test_worker_tick.py).
_worker = Path(__file__).parents[2] / "worker"
if str(_worker) not in sys.path:
    sys.path.insert(0, str(_worker))

import scheduler  # noqa: E402


def test_resolve_asset_classes_default(monkeypatch):
    monkeypatch.setattr("config.settings.self_evolve_asset_classes", "")
    assert scheduler.resolve_asset_classes(["equity", "crypto"]) == ["equity", "crypto"]


def test_resolve_asset_classes_override(monkeypatch):
    monkeypatch.setattr("config.settings.self_evolve_asset_classes", "forex, option")
    assert scheduler.resolve_asset_classes(["equity"]) == ["forex", "option"]


class _FakeSession:
    def __init__(self):
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_label_and_evaluate_job_runs_per_asset_class(monkeypatch):
    sess = _FakeSession()
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: sess)

    label = AsyncMock(return_value=3)
    evaluate = AsyncMock()
    champ = AsyncMock(return_value=None)
    monkeypatch.setattr("ml.labeling.label_outcomes", label)
    monkeypatch.setattr("ml.evaluation.evaluate_model", evaluate)
    monkeypatch.setattr("ml.promotion.get_champion_version", champ)

    await scheduler.label_and_evaluate_job(["equity", "crypto"])

    assert label.await_count == 2
    assert evaluate.await_count == 2
    assert sess.committed is True


@pytest.mark.asyncio
async def test_train_and_propose_job_uses_injected_trainer(monkeypatch):
    sess = _FakeSession()
    sess.add = MagicMock()
    sess.flush = AsyncMock()
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: sess)

    propose = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr("ml.promotion.propose_promotion", propose)

    def trainer(asset_class, version):
        return {"val_accuracy": 0.63, "n_val": 120}

    await scheduler.train_and_propose_job(["equity"], trainer=trainer)

    sess.add.assert_called_once()           # candidate evaluation row written
    propose.assert_awaited_once()


@pytest.mark.asyncio
async def test_train_and_propose_skips_when_trainer_returns_none(monkeypatch):
    sess = _FakeSession()
    sess.add = MagicMock()
    sess.flush = AsyncMock()
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: sess)
    propose = AsyncMock()
    monkeypatch.setattr("ml.promotion.propose_promotion", propose)

    await scheduler.train_and_propose_job(["equity"], trainer=lambda ac, v: None)

    sess.add.assert_not_called()
    propose.assert_not_awaited()


@pytest.mark.asyncio
async def test_equity_snapshot_job_writes_point(monkeypatch):
    sess = _FakeSession()
    sess.add = MagicMock()
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: sess)

    # Empty position set → snapshot still records a base-equity point.
    class _Res:
        def scalars(self):
            return MagicMock(all=lambda: [])
    sess.execute = AsyncMock(return_value=_Res())

    await scheduler.equity_snapshot_job()
    sess.add.assert_called_once()
    assert sess.committed is True


def test_build_scheduler_registers_jobs(monkeypatch):
    pytest.importorskip("apscheduler")
    monkeypatch.setattr("config.settings.self_evolve_asset_classes", "")
    sched = scheduler.build_scheduler(["equity"])
    try:
        ids = {j.id for j in sched.get_jobs()}
        assert ids == {"label_and_evaluate", "train_and_propose", "equity_snapshot"}
    finally:
        sched.shutdown(wait=False) if sched.running else None
