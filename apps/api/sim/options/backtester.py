"""Options backtester — purged walk-forward evaluation (doc §8 Gate 4).

Real historical option chains are thin via Moomoo, so the alpha backtests
**synthetic** single-leg options priced off the underlying with Black-Scholes
(entry IV from realized vol). This validates entry/exit/sizing logic and the
purged walk-forward machinery now; swap in collected real chains later without
changing the split logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

import numpy as np
import pandas as pd

from options_math import bs_price, implied_vol  # noqa: F401 (implied_vol used by callers)
from .fill_model import simulate_option_fill
from .lifecycle import intrinsic_value

Right = Literal["call", "put"]


# ---------------------------------------------------------------------------
# Purged walk-forward splits
# ---------------------------------------------------------------------------

def purged_walkforward_splits(
    n: int, n_splits: int = 5, embargo: int = 0,
) -> list[tuple[range, range]]:
    """Sequential expanding-window splits with a purge/embargo gap.

    Returns [(train_idx, test_idx), ...]. Train is always strictly before its
    test block; the last `embargo` train samples are purged so a label whose
    horizon overlaps the test window can't leak. Train/test never overlap.
    """
    if n <= 0 or n_splits < 1:
        return []
    fold = n // (n_splits + 1)
    if fold == 0:
        return []
    splits: list[tuple[range, range]] = []
    for i in range(1, n_splits + 1):
        train_end = fold * i
        test_start = train_end + embargo
        test_end = n if i == n_splits else fold * (i + 1)
        if test_start >= test_end:
            continue
        train_stop = max(0, train_end - embargo)
        if train_stop <= 0:
            continue
        splits.append((range(0, train_stop), range(test_start, test_end)))
    return splits


# ---------------------------------------------------------------------------
# Synthetic single-leg backtest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Trade:
    entry_ts: object
    exit_ts: object
    right: Right
    strike: float
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    outcome: str


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    sharpe: float = 0.0
    n_trades: int = 0

    @classmethod
    def from_trades(cls, trades: list[Trade]) -> "BacktestResult":
        if not trades:
            return cls()
        pnls = np.array([t.pnl for t in trades], dtype=float)
        wins = float((pnls > 0).mean())
        sharpe = float(pnls.mean() / pnls.std(ddof=1)) if len(pnls) > 1 and pnls.std(ddof=1) > 0 else 0.0
        return cls(
            trades=trades, total_pnl=float(pnls.sum()), win_rate=wins,
            avg_pnl=float(pnls.mean()), sharpe=sharpe, n_trades=len(trades),
        )


# signal_fn(window_df) -> "call" | "put" | None  (None = no trade this bar)
SignalFn = Callable[[pd.DataFrame], Optional[Right]]


def backtest_single_leg(
    bars: pd.DataFrame,
    signal_fn: SignalFn,
    *,
    hold_days: int = 5,
    dte: int = 30,
    r: float = 0.05,
    vol_lookback: int = 20,
    moneyness: float = 1.0,          # strike = moneyness * spot (1.0 = ATM)
    qty: float = 1.0,
    multiplier: int = 100,
    commission_per_contract: float = 0.65,
    aggression: float = 0.5,
) -> BacktestResult:
    """Backtest a synthetic single-leg long-option strategy on daily `bars`.

    `bars` needs a lowercase `close` column and a datetime index. Each bar,
    `signal_fn` may emit "call"/"put"; we buy a `dte`-day option struck at
    `moneyness`*spot, priced by BS with sigma = trailing realized vol, hold
    `hold_days`, then mark out at the prevailing BS value (intrinsic if expired).
    """
    close = pd.to_numeric(bars["close"], errors="coerce").dropna()
    if len(close) < vol_lookback + hold_days + 2:
        return BacktestResult()

    logret = np.log(close / close.shift(1))
    realized = logret.rolling(vol_lookback).std() * np.sqrt(252)

    trades: list[Trade] = []
    i = vol_lookback
    n = len(close)
    while i < n - hold_days:
        window = bars.iloc[: i + 1]
        right = signal_fn(window)
        if right not in ("call", "put"):
            i += 1
            continue

        sigma = float(realized.iloc[i])
        if not np.isfinite(sigma) or sigma <= 0:
            i += 1
            continue

        spot = float(close.iloc[i])
        strike = round(moneyness * spot, 2)
        T = dte / 365.0
        theo = bs_price(spot, strike, T, r, sigma, right)

        entry = simulate_option_fill(
            bid=theo * 0.98, ask=theo * 1.02, last=theo, side="buy", qty=qty,
            aggression=aggression, commission_per_contract=commission_per_contract,
            multiplier=multiplier, partial_fill_pct=1.0,
        )
        if not entry.filled:
            i += 1
            continue

        j = i + hold_days
        spot_exit = float(close.iloc[j])
        T_exit = max(0.0, (dte - hold_days) / 365.0)
        if T_exit <= 0:
            exit_theo = intrinsic_value(right, spot_exit, strike)
            outcome = "expired"
        else:
            exit_theo = bs_price(spot_exit, strike, T_exit, r, sigma, right)
            outcome = "closed"
        exit_fill = simulate_option_fill(
            bid=exit_theo * 0.98, ask=exit_theo * 1.02, last=exit_theo, side="sell", qty=entry.qty,
            aggression=aggression, commission_per_contract=commission_per_contract,
            multiplier=multiplier, partial_fill_pct=1.0,
        )
        exit_price = exit_fill.price if exit_fill.filled else max(0.0, exit_theo)

        pnl = (exit_price - entry.price) * multiplier * entry.qty - entry.commission - exit_fill.commission
        trades.append(Trade(
            entry_ts=close.index[i], exit_ts=close.index[j], right=right, strike=strike,
            entry_price=entry.price, exit_price=exit_price, qty=entry.qty, pnl=pnl, outcome=outcome,
        ))
        i = j  # non-overlapping trades

    return BacktestResult.from_trades(trades)
