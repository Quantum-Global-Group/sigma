"""The single place the alpha win-condition lives.

Every edge-research harness reduces to the same shape: a set of trades, each with
a realized gross return, judged net of cost on a held-out tail. This module owns
that judgment so the three research theses (event drift, stat-arb, less-liquid
technical) cannot each invent their own — the reason the forex "lead" looked real
until an honest split killed it.

Pure and unit-tested. Costs/Sharpe/drawdown reuse `ml.costs`; the split reuses the
chronological discipline from `ml.cv`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

from ml import costs

# Pre-registered gate (identical for every thesis — do not loosen per-experiment).
GATE_MIN_TRADES = 100


@dataclass(frozen=True)
class TradeStats:
    n: int
    win_rate: float
    gross_bps: float          # mean gross return per trade, in bps
    net_bps: float            # mean net (after round-trip cost) per trade, in bps
    sharpe: float             # per-trade mean/std of net returns (not annualized)
    total_pct: float          # summed net return over all trades, in %
    max_dd_pct: float

    def as_dict(self) -> dict:
        return asdict(self)


def trade_stats(gross_returns: Sequence[float], *, cost_frac: float,
                round_trips: float = 1.0) -> TradeStats:
    """Net-of-cost economics for a set of trades.

    `gross_returns` are realized signed per-trade returns (e.g. side_pnl of a
    triple-barrier hold). Each trade pays `round_trips * cost_frac` once — a hold
    to a barrier is one round trip; a 2-leg spread trade is two."""
    g = np.asarray(gross_returns, dtype=float)
    n = int(g.size)
    if n == 0:
        return TradeStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    net = g - round_trips * cost_frac
    sh = costs.sharpe(net, periods_per_year=1)  # per-trade mean/std (sqrt(1)=1)
    return TradeStats(
        n=n,
        win_rate=float(np.mean(g > 0)),
        gross_bps=float(g.mean() * 1e4),
        net_bps=float(net.mean() * 1e4),
        sharpe=float(sh) if sh is not None else 0.0,
        total_pct=float(net.sum() * 100.0),
        max_dd_pct=float(costs.max_drawdown(net) * 100.0),
    )


def gate(stats: TradeStats, *, min_trades: int = GATE_MIN_TRADES) -> tuple[bool, list[str]]:
    """PASS only if net-positive AND positive per-trade Sharpe AND enough trades.

    Returns (passed, reasons-for-failure). A single marginal bucket among many is
    still noise — callers must also supply a coherent story; this enforces the
    quantitative floor."""
    reasons: list[str] = []
    if stats.n < min_trades:
        reasons.append(f"only {stats.n} trades (< {min_trades})")
    if stats.net_bps <= 0:
        reasons.append(f"net {stats.net_bps:.2f} bps/trade is not positive")
    if stats.sharpe <= 0:
        reasons.append(f"per-trade Sharpe {stats.sharpe:.3f} is not positive")
    return (not reasons, reasons)


def chrono_split(timestamps: Sequence, train_frac: float = 0.6) -> tuple[np.ndarray, np.ndarray]:
    """Boolean (train_mask, test_mask): earliest `train_frac` by time is train.

    Pooling across symbols is fine — the split is purely temporal, so no future
    bar trains on a past one regardless of symbol order."""
    ts = np.asarray(timestamps)
    n = len(ts)
    if n == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)
    order = np.argsort(ts, kind="mergesort")
    cut = int(n * train_frac)
    train = np.zeros(n, dtype=bool)
    train[order[:cut]] = True
    return train, ~train


def format_row(label: str, stats: TradeStats) -> str:
    return (f"  {label:<24}{stats.n:>7} trades  win {stats.win_rate*100:>5.1f}%  "
            f"gross {stats.gross_bps:>7.2f}  net {stats.net_bps:>7.2f}bps  "
            f"sharpe {stats.sharpe:>6.3f}  total {stats.total_pct:>7.2f}%  "
            f"maxDD {stats.max_dd_pct:>6.2f}%")


def verdict(label: str, stats: TradeStats, *, min_trades: int = GATE_MIN_TRADES) -> str:
    ok, reasons = gate(stats, min_trades=min_trades)
    if ok:
        return (f"  VERDICT {label}: PASS — net {stats.net_bps:.2f} bps/trade, "
                f"Sharpe {stats.sharpe:.3f}, n={stats.n}. Worth a productionization plan.")
    return f"  VERDICT {label}: REJECT — {'; '.join(reasons)}."
