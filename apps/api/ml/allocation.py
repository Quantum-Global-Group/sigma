"""Trend-filtered diversified allocation — the one strategy that cleared the bar.

After a research program in which every market-neutral / directional alpha
candidate rejected out of sample (see docs/MODELS.md), the one thing that
survived a cross-regime, cost-aware test was *risk-managed beta*: hold a
diversified book, but only the sleeves currently above their N-month moving
average; the rest sits in cash. Monthly rebalance. 2005-2026 incl. 2008/2020/2022:
Sharpe 1.25 vs 0.78 (SPY), max drawdown −12.5% vs −51%, positive in 2008
(`scripts/retail_portfolio_backtest.py`).

This is the deployable strategy — honest about what it is (smarter beta, not
alpha). Pure and unit-tested; the worker (`apps/worker/allocation_tick.py`) wires
it to data, the executor, and a monthly cadence.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def parse_weights(csv: str) -> dict[str, float]:
    """'SPY:0.30,TLT:0.15,...' → normalized weights summing to 1.0.

    Normalizing means the configured ratios are what matter, not whether they
    happen to sum to 1 — the trend filter later zeroes sleeves to cash."""
    raw: dict[str, float] = {}
    for part in csv.split(","):
        if ":" in part:
            sym, w = part.split(":", 1)
            try:
                v = float(w)
            except ValueError:
                continue
            if v > 0:
                raw[sym.strip().upper()] = v
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total > 0 else {}


def in_trend(daily_close: pd.Series, ma_months: int) -> bool:
    """True if the latest monthly close is above its `ma_months`-month average.

    Not enough history (< ma_months+1 months) → True (hold rather than sit out a
    sleeve we can't yet judge). Strictly uses only closed data passed in."""
    m = pd.Series(daily_close).dropna().resample("ME").last() if _has_dt_index(daily_close) \
        else pd.Series(daily_close).dropna()
    if len(m) < ma_months + 1:
        return True
    ma = m.rolling(ma_months).mean().iloc[-1]
    return bool(m.iloc[-1] > ma)


def _has_dt_index(s) -> bool:
    return isinstance(getattr(s, "index", None), pd.DatetimeIndex)


def target_weights(prices: dict[str, pd.Series], base_weights: dict[str, float],
                   ma_months: int = 10) -> dict[str, float]:
    """Trend-filtered target weights: base weight if the sleeve is in trend, else
    0 (that capital is held in cash). Sum ≤ 1; the remainder is the cash buffer
    that de-risks the book in downtrends."""
    out: dict[str, float] = {}
    for sym, w in base_weights.items():
        px = prices.get(sym)
        out[sym] = float(w) if (px is not None and len(px) and in_trend(px, ma_months)) else 0.0
    return out


@dataclass(frozen=True)
class RebalanceOrder:
    symbol: str
    side: str        # "buy" | "sell"
    qty: float
    notional: float


def rebalance_orders(
    targets: dict[str, float],
    equity: float,
    current_qty: dict[str, float],
    last_price: dict[str, float],
    *,
    min_trade_usd: float = 50.0,
) -> list[RebalanceOrder]:
    """Orders to move the book from `current_qty` toward `targets`·`equity`.

    Sells sleeves that fell out of trend (target 0) and any holding not in the
    target set. Skips dust trades below `min_trade_usd` so a monthly rebalance
    doesn't churn on tiny drifts. Pure — no IO."""
    orders: list[RebalanceOrder] = []
    symbols = set(targets) | set(current_qty)
    for sym in sorted(symbols):
        price = float(last_price.get(sym, 0.0))
        if price <= 0:
            continue
        target_val = float(equity) * float(targets.get(sym, 0.0))
        current_val = float(current_qty.get(sym, 0.0)) * price
        delta = target_val - current_val
        if abs(delta) < min_trade_usd:
            continue
        orders.append(RebalanceOrder(
            symbol=sym,
            side="buy" if delta > 0 else "sell",
            qty=abs(delta) / price,
            notional=abs(delta),
        ))
    return orders
