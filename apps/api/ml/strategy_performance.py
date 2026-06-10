"""Aggregate per-strategy stats from labeled signal_history rows.

Reads `component_weights.component_signals` / `component_confidence` and joins
to `outcome` / `realized_return` for win-rate reporting when a strategy's
strength exceeds a configurable threshold (default 0.3 for ICT-style queries).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

_PERIOD_RE = re.compile(r"^(\d+)([dh])$")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SignalHistory


@dataclass
class StrategyStats:
    strategy: str
    n_signals: int = 0
    contribution_count: int = 0
    contribution_frequency: float = 0.0
    avg_strength_when_present: Optional[float] = None
    n_above_threshold: int = 0
    n_labeled_above_threshold: int = 0
    win_rate_above_threshold: Optional[float] = None
    avg_realized_return_above_threshold: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "n_signals": self.n_signals,
            "contribution_count": self.contribution_count,
            "contribution_frequency": round(self.contribution_frequency, 4),
            "avg_strength_when_present": (
                round(self.avg_strength_when_present, 4)
                if self.avg_strength_when_present is not None else None
            ),
            "n_above_threshold": self.n_above_threshold,
            "n_labeled_above_threshold": self.n_labeled_above_threshold,
            "win_rate_above_threshold": (
                round(self.win_rate_above_threshold, 4)
                if self.win_rate_above_threshold is not None else None
            ),
            "avg_realized_return_above_threshold": (
                round(self.avg_realized_return_above_threshold, 6)
                if self.avg_realized_return_above_threshold is not None else None
            ),
        }


@dataclass
class _Accum:
    n_signals: int = 0
    contribution_count: int = 0
    strength_sum: float = 0.0
    strength_n: int = 0
    n_above_threshold: int = 0
    wins: int = 0
    losses: int = 0
    labeled_above: int = 0
    return_sum: float = 0.0


def _component_maps(cw: dict | None) -> tuple[dict[str, float], dict[str, float]]:
    if not cw:
        return {}, {}
    raw_signals = cw.get("component_signals") or {}
    raw_conf = cw.get("component_confidence") or {}
    signals = {str(k): float(v) for k, v in raw_signals.items()}
    confidences = {str(k): float(v) for k, v in raw_conf.items()}
    return signals, confidences


def aggregate_strategy_stats(
    rows: list[Any],
    *,
    strength_threshold: float = 0.3,
    contribution_epsilon: float = 0.01,
) -> list[StrategyStats]:
    """Pure aggregation over signal_history-like rows (ORM or dicts)."""
    acc: dict[str, _Accum] = defaultdict(_Accum)
    total = len(rows)

    for row in rows:
        cw = row.component_weights if hasattr(row, "component_weights") else row.get("component_weights")
        outcome = row.outcome if hasattr(row, "outcome") else row.get("outcome")
        realized = row.realized_return if hasattr(row, "realized_return") else row.get("realized_return")
        signals, _ = _component_maps(cw)
        if not signals:
            continue
        for name, strength in signals.items():
            a = acc[name]
            a.n_signals = total
            if abs(strength) >= contribution_epsilon:
                a.contribution_count += 1
                a.strength_sum += strength
                a.strength_n += 1
            if strength > strength_threshold:
                a.n_above_threshold += 1
                if outcome in ("win", "loss"):
                    a.labeled_above += 1
                    if outcome == "win":
                        a.wins += 1
                    else:
                        a.losses += 1
                    if realized is not None:
                        a.return_sum += float(realized)

    out: list[StrategyStats] = []
    for name, a in sorted(acc.items()):
        freq = (a.contribution_count / total) if total else 0.0
        avg_strength = (a.strength_sum / a.strength_n) if a.strength_n else None
        win_rate = None
        if a.labeled_above > 0:
            win_rate = a.wins / a.labeled_above
        avg_ret = (a.return_sum / a.labeled_above) if a.labeled_above else None
        out.append(StrategyStats(
            strategy=name,
            n_signals=total,
            contribution_count=a.contribution_count,
            contribution_frequency=freq,
            avg_strength_when_present=avg_strength,
            n_above_threshold=a.n_above_threshold,
            n_labeled_above_threshold=a.labeled_above,
            win_rate_above_threshold=win_rate,
            avg_realized_return_above_threshold=avg_ret,
        ))
    return out


def parse_period(period: str) -> timedelta:
    """Parse duration strings like ``7d`` or ``24h`` into a timedelta."""
    m = _PERIOD_RE.match(period.strip().lower())
    if not m:
        raise ValueError(f"invalid period {period!r}; use e.g. 7d or 24h")
    n, unit = int(m.group(1)), m.group(2)
    if n <= 0:
        raise ValueError(f"period must be positive, got {period!r}")
    return timedelta(days=n) if unit == "d" else timedelta(hours=n)


def resolve_since(
    *,
    period: Optional[str] = None,
    since: Optional[datetime] = None,
) -> tuple[Optional[datetime], Optional[str]]:
    """Return (since_ts, normalized_period). ``period`` wins over explicit ``since``."""
    if period:
        return datetime.now(timezone.utc) - parse_period(period), period.strip().lower()
    return since, None


def build_strategy_report_summary(data: dict[str, Any]) -> str:
    """Markdown summary for strategy performance reports (weekly review habit)."""
    ac = data.get("asset_class", "equity")
    period = data.get("period") or "all-time"
    n_signals = data.get("n_signals", 0)
    n_labeled = data.get("n_labeled", 0)
    threshold = data.get("strength_threshold", 0.3)
    since = data.get("since")

    lines = [
        f"# Strategy report — {ac} ({period})",
        "",
        f"Window: **{since or 'all signals in sample'}** → now",
        f"Signals: **{n_signals}** ({n_labeled} labeled) · strength threshold **{threshold}**",
        "",
        "## Per-strategy stats",
        "",
        "| strategy | contribution | avg strength | win rate (> thr) | n above thr |",
        "|---|---|---|---|---|",
    ]
    strategies = data.get("strategies") or []
    if not strategies:
        lines.append("| — | — | — | — | — |")
    else:
        for s in sorted(strategies, key=lambda x: x.get("contribution_frequency") or 0, reverse=True):
            freq = s.get("contribution_frequency")
            freq_s = f"{freq * 100:.1f}%" if freq is not None else "—"
            avg = s.get("avg_strength_when_present")
            avg_s = f"{avg:.3f}" if avg is not None else "—"
            wr = s.get("win_rate_above_threshold")
            wr_s = f"{wr * 100:.1f}%" if wr is not None else "—"
            lines.append(
                f"| {s.get('strategy', '?')} | {freq_s} | {avg_s} | {wr_s} | {s.get('n_above_threshold', 0)} |"
            )
    lines.extend(["", "_Generated from signal_history component_weights._"])
    return "\n".join(lines)


async def fetch_strategy_performance(
    session: AsyncSession,
    *,
    asset_class: str,
    since: Optional[datetime] = None,
    period: Optional[str] = None,
    strength_threshold: float = 0.3,
    limit: int = 5000,
    include_summary: bool = True,
) -> dict[str, Any]:
    since, normalized_period = resolve_since(period=period, since=since)
    q = (
        select(SignalHistory)
        .where(SignalHistory.asset_class == asset_class)
        .order_by(SignalHistory.created_at.desc())
        .limit(limit)
    )
    if since is not None:
        q = q.where(SignalHistory.created_at >= since)
    rows = list((await session.execute(q)).scalars().all())
    stats = aggregate_strategy_stats(rows, strength_threshold=strength_threshold)
    labeled = sum(1 for r in rows if r.outcome is not None)
    payload: dict[str, Any] = {
        "asset_class": asset_class,
        "period": normalized_period,
        "since": since.isoformat() if since else None,
        "strength_threshold": strength_threshold,
        "n_signals": len(rows),
        "n_labeled": labeled,
        "strategies": [s.to_dict() for s in stats],
    }
    if include_summary:
        payload["summary"] = build_strategy_report_summary(payload)
    return payload
