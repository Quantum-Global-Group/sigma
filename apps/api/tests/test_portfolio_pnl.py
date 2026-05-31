"""Portfolio P&L aggregation + equity snapshot tests (PR-G)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from risk.portfolio_pnl import aggregate_pnl, snapshot_equity


def _pos(asset_class, realized, unrealized, closed=False):
    return SimpleNamespace(asset_class=asset_class, realized_pnl=realized,
                           unrealized_pnl=unrealized, closed=closed)


def test_aggregate_pnl_totals_and_breakdown():
    positions = [
        _pos("equity", 100.0, 50.0),
        _pos("equity", 0.0, -20.0),
        _pos("forex", 30.0, 10.0),
        _pos("option", 200.0, 0.0, closed=True),   # closed → no unrealized, no open count
    ]
    s = aggregate_pnl(positions)
    assert s.total_realized == pytest.approx(330.0)
    assert s.total_unrealized == pytest.approx(40.0)        # 50 - 20 + 10 (closed excluded)
    assert s.total_pnl == pytest.approx(370.0)
    assert s.open_positions == 3
    assert s.by_asset_class["equity"].realized == pytest.approx(100.0)
    assert s.by_asset_class["equity"].unrealized == pytest.approx(30.0)
    assert s.by_asset_class["equity"].open_positions == 2
    assert s.by_asset_class["option"].realized == pytest.approx(200.0)
    assert s.by_asset_class["option"].open_positions == 0


def test_aggregate_pnl_handles_none_values():
    s = aggregate_pnl([_pos("crypto", None, None)])
    assert s.total_realized == 0.0 and s.total_unrealized == 0.0


def test_pnl_summary_to_dict_shape():
    s = aggregate_pnl([_pos("forex", 30.0, 10.0)])
    d = s.to_dict()
    assert d["total_pnl"] == pytest.approx(40.0)
    assert d["by_asset_class"]["forex"]["total"] == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_snapshot_equity_writes_row():
    positions = [_pos("equity", 100.0, 50.0), _pos("forex", 0.0, 25.0)]
    session = MagicMock()
    session.add = MagicMock()
    snap = await snapshot_equity(session, positions, base_equity=10_000.0)
    session.add.assert_called_once()
    # total_value = base + realized + unrealized = 10000 + 100 + 75
    assert float(snap.total_value) == pytest.approx(10_175.0)
    assert float(snap.total_unrealized) == pytest.approx(75.0)
