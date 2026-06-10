"""Model-promotion tests (PR-E) — propose gate + approve/reject (mock session)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import ml.promotion as promo


def _eval(version, acc, n):
    return SimpleNamespace(model_version=version, directional_accuracy=acc, n_samples=n)


@pytest.mark.asyncio
async def test_propose_promotion_files_when_candidate_better(monkeypatch):
    session = MagicMock()
    session.add = MagicMock()

    monkeypatch.setattr(promo, "get_champion_version", AsyncMock(return_value="v1.0"))
    monkeypatch.setattr(promo, "_pending_exists", AsyncMock(return_value=False))

    async def fake_latest(session, ac, mt, version):
        return {"cand-x": _eval("cand-x", 0.62, 200), "v1.0": _eval("v1.0", 0.55, 300)}[version]
    monkeypatch.setattr(promo, "_latest_eval", fake_latest)

    out = await promo.propose_promotion(session, "equity", "cand-x",
                                        min_improvement=0.02, min_samples=50)
    assert out is not None
    assert out.status == "pending" and out.to_version == "cand-x" and out.from_version == "v1.0"
    assert out.rationale["improvement"] == pytest.approx(0.07, abs=1e-9)
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_propose_skips_when_improvement_below_threshold(monkeypatch):
    session = MagicMock(); session.add = MagicMock()
    monkeypatch.setattr(promo, "get_champion_version", AsyncMock(return_value="v1.0"))
    monkeypatch.setattr(promo, "_pending_exists", AsyncMock(return_value=False))

    async def fake_latest(session, ac, mt, version):
        return {"cand-x": _eval("cand-x", 0.56, 200), "v1.0": _eval("v1.0", 0.55, 300)}[version]
    monkeypatch.setattr(promo, "_latest_eval", fake_latest)

    out = await promo.propose_promotion(session, "equity", "cand-x", min_improvement=0.02, min_samples=50)
    assert out is None
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_propose_skips_when_too_few_samples(monkeypatch):
    session = MagicMock(); session.add = MagicMock()
    monkeypatch.setattr(promo, "get_champion_version", AsyncMock(return_value="v1.0"))
    monkeypatch.setattr(promo, "_pending_exists", AsyncMock(return_value=False))

    async def fake_latest(session, ac, mt, version):
        return _eval(version, 0.90, 10) if version == "cand-x" else _eval(version, 0.55, 300)
    monkeypatch.setattr(promo, "_latest_eval", fake_latest)

    out = await promo.propose_promotion(session, "equity", "cand-x", min_improvement=0.02, min_samples=50)
    assert out is None


@pytest.mark.asyncio
async def test_approve_promotion_flips_champion(monkeypatch):
    fake_promo = SimpleNamespace(
        status="pending", asset_class="equity", model_type="ensemble",
        from_version="v1.0", to_version="cand-x", decided_at=None, decided_by=None,
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=fake_promo)

    out = await promo.approve_promotion(session, "some-id", decided_by="tester")
    assert out.status == "approved" and out.decided_by == "tester"
    # _set_champion issues an upsert via session.execute
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_promotion(monkeypatch):
    fake_promo = SimpleNamespace(status="pending", decided_at=None, decided_by=None)
    session = AsyncMock()
    session.get = AsyncMock(return_value=fake_promo)
    out = await promo.reject_promotion(session, "id", decided_by="tester")
    assert out.status == "rejected"


@pytest.mark.asyncio
async def test_approve_noop_when_not_pending():
    fake_promo = SimpleNamespace(status="approved")
    session = AsyncMock()
    session.get = AsyncMock(return_value=fake_promo)
    out = await promo.approve_promotion(session, "id")
    assert out.status == "approved"
    session.execute.assert_not_awaited()
