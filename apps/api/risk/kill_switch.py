"""Kill switch — a single hard halt for all new option entries (doc §8 Gate 5).

A tripped switch blocks new buys until explicitly reset. Trip conditions are
pure evaluators (data quality, portfolio loss, drawdown, Greek breaches) so the
worker can feed live state in and the decision is testable. In-memory for the
alpha; back with Redis later for multi-process coordination.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class KillSwitch:
    tripped: bool = False
    reason: Optional[str] = None
    tripped_at: Optional[datetime] = None
    history: list[dict] = field(default_factory=list)

    def trip(self, reason: str) -> None:
        if not self.tripped:
            self.tripped = True
            self.reason = reason
            self.tripped_at = datetime.now(timezone.utc)
            self.history.append({"event": "trip", "reason": reason, "ts": self.tripped_at.isoformat()})
            logger.error("KILL SWITCH TRIPPED: %s", reason)

    def reset(self) -> None:
        self.history.append({
            "event": "reset", "prev_reason": self.reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        self.tripped = False
        self.reason = None
        self.tripped_at = None
        logger.warning("kill switch reset")

    def allow_new_entries(self) -> bool:
        return not self.tripped


@dataclass(frozen=True)
class HaltThresholds:
    max_portfolio_loss_pct: float = 0.10   # cumulative loss vs starting equity
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.20


def evaluate_halt(
    *,
    equity: float,
    starting_equity: float,
    daily_pnl: float,
    peak_equity: float,
    thresholds: HaltThresholds,
    data_ok: bool = True,
    greek_breaches: Optional[list[str]] = None,
) -> tuple[bool, list[str]]:
    """Return (should_halt, reasons) from live risk state. Pure — the caller
    owns the KillSwitch instance and decides to .trip()."""
    reasons: list[str] = []

    if not data_ok:
        reasons.append("data quality failure")
    if greek_breaches:
        reasons.extend(greek_breaches)

    if starting_equity > 0:
        cum_loss = (starting_equity - equity) / starting_equity
        if cum_loss > thresholds.max_portfolio_loss_pct:
            reasons.append(f"portfolio loss {cum_loss:.1%} > {thresholds.max_portfolio_loss_pct:.0%}")
        daily_loss = -daily_pnl / starting_equity
        if daily_loss > thresholds.max_daily_loss_pct:
            reasons.append(f"daily loss {daily_loss:.1%} > {thresholds.max_daily_loss_pct:.0%}")

    if peak_equity > 0:
        dd = (peak_equity - equity) / peak_equity
        if dd > thresholds.max_drawdown_pct:
            reasons.append(f"drawdown {dd:.1%} > {thresholds.max_drawdown_pct:.0%}")

    return (len(reasons) > 0, reasons)
