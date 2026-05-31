"""Portfolio-level P&L aggregation + equity snapshots.

`aggregate_pnl` sums realized + unrealized P&L across positions into totals and a
per-asset-class breakdown (pure — testable on plain position rows). The worker
tick keeps `unrealized_pnl` fresh via mark-to-market (risk/pnl.py); this just
rolls it up. `snapshot_equity` persists a point on the equity curve.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EquitySnapshot


@dataclass
class AssetClassPnl:
    realized: float = 0.0
    unrealized: float = 0.0
    open_positions: int = 0

    @property
    def total(self) -> float:
        return self.realized + self.unrealized


@dataclass
class PnlSummary:
    total_realized: float = 0.0
    total_unrealized: float = 0.0
    open_positions: int = 0
    by_asset_class: dict[str, AssetClassPnl] = field(default_factory=dict)

    @property
    def total_pnl(self) -> float:
        return self.total_realized + self.total_unrealized

    def to_dict(self) -> dict:
        return {
            "total_realized": round(self.total_realized, 2),
            "total_unrealized": round(self.total_unrealized, 2),
            "total_pnl": round(self.total_pnl, 2),
            "open_positions": self.open_positions,
            "by_asset_class": {
                ac: {**asdict(v), "total": round(v.total, 2)}
                for ac, v in self.by_asset_class.items()
            },
        }


def aggregate_pnl(positions: Iterable) -> PnlSummary:
    """Roll up realized + unrealized P&L across positions. Pure.

    Each position needs: asset_class, realized_pnl, unrealized_pnl, closed.
    Realized counts for all positions; unrealized + open counts only for open."""
    summary = PnlSummary()
    for p in positions:
        ac = getattr(p, "asset_class", "unknown")
        bucket = summary.by_asset_class.setdefault(ac, AssetClassPnl())

        realized = float(getattr(p, "realized_pnl", 0.0) or 0.0)
        bucket.realized += realized
        summary.total_realized += realized

        if not getattr(p, "closed", False):
            unreal = float(getattr(p, "unrealized_pnl", 0.0) or 0.0)
            bucket.unrealized += unreal
            summary.total_unrealized += unreal
            bucket.open_positions += 1
            summary.open_positions += 1
    return summary


async def snapshot_equity(session: AsyncSession, positions: Iterable, base_equity: float) -> EquitySnapshot:
    """Compute the P&L summary and persist one equity-curve point.

    total_value = base_equity + realized + unrealized (paper book convention).
    The caller owns the transaction."""
    s = aggregate_pnl(positions)
    total_value = base_equity + s.total_realized + s.total_unrealized
    row = EquitySnapshot(
        ts=datetime.now(timezone.utc),
        base_equity=round(base_equity, 2),
        total_realized=round(s.total_realized, 2),
        total_unrealized=round(s.total_unrealized, 2),
        total_value=round(total_value, 2),
        by_asset_class=s.to_dict()["by_asset_class"],
    )
    session.add(row)
    return row
