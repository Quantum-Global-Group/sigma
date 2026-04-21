"""
Vectorized event-driven backtest engine.

Strategy: equal-weight allocation across requested tickers, rebalanced on the
specified frequency. Computes equity curve via cumulative returns; reports
total/annualized return, Sharpe ratio, and max drawdown.

This is a deliberately simple baseline — the heavy lifting (signal-driven
rebalancing) plugs in once trained models exist (Week 3 Day 15).
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, status

from db.models import APIKey, User
from middleware.auth import require_api_key
from middleware.rate_limit import check_rate_limit
from models.backtest import BacktestRequest, BacktestResult, EquityPoint, TradeEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])

AuthDep = Annotated[tuple[APIKey, User], Depends(require_api_key)]

REBALANCE_RULES = {
    "daily": "B",      # business day
    "weekly": "W-MON",
    "monthly": "MS",   # month start
}


def _fetch_panel(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Return adjusted close panel (rows=date, cols=ticker)."""
    data = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True, group_by="ticker")
    if data is None or data.empty:
        raise ValueError("No historical data returned for the requested window")

    if isinstance(data.columns, pd.MultiIndex):
        closes = pd.DataFrame({t: data[t]["Close"] for t in tickers if t in data.columns.get_level_values(0)})
    else:
        # Single ticker — yfinance returns flat columns
        closes = data[["Close"]].rename(columns={"Close": tickers[0]})

    closes = closes.dropna(how="all").ffill().dropna()
    if closes.empty:
        raise ValueError("No overlapping price data across tickers")
    return closes


def _run_backtest(req: BacktestRequest) -> BacktestResult:
    closes = _fetch_panel(req.tickers, req.start_date, req.end_date)
    daily_returns = closes.pct_change().fillna(0.0)
    n_assets = len(req.tickers)

    rebalance_rule = REBALANCE_RULES[req.rebalance_freq]
    rebalance_dates = closes.resample(rebalance_rule).first().index.intersection(closes.index)

    weights_target = np.ones(n_assets) / n_assets
    portfolio_value = req.initial_capital
    equity_curve: list[EquityPoint] = []
    trade_log: list[TradeEntry] = []

    weights = np.copy(weights_target)
    for date, row_returns in daily_returns.iterrows():
        # Apply daily returns
        asset_returns = row_returns.values
        portfolio_return = float(np.dot(weights, asset_returns))
        portfolio_value *= 1.0 + portfolio_return
        # Drift weights by realized returns
        drifted = weights * (1.0 + asset_returns)
        weights = drifted / drifted.sum() if drifted.sum() > 0 else weights_target.copy()

        # Rebalance on the chosen frequency
        if date in rebalance_dates:
            weights = weights_target.copy()
            for i, ticker in enumerate(req.tickers):
                trade_log.append(TradeEntry(
                    date=date.strftime("%Y-%m-%d"),
                    ticker=ticker,
                    action="REBALANCE",
                    weight=round(float(weights_target[i]), 4),
                ))

        equity_curve.append(EquityPoint(date=date.strftime("%Y-%m-%d"), value=round(portfolio_value, 2)))

    final_value = portfolio_value
    total_return = (final_value / req.initial_capital) - 1.0
    n_days = len(equity_curve)
    annualized_return = (1.0 + total_return) ** (252.0 / max(n_days, 1)) - 1.0

    portfolio_returns = pd.Series([p.value for p in equity_curve]).pct_change().dropna()
    sharpe = (
        float(portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252))
        if portfolio_returns.std() > 0
        else 0.0
    )

    cum = pd.Series([p.value for p in equity_curve])
    running_max = cum.cummax()
    drawdown = (cum / running_max) - 1.0
    max_drawdown = float(drawdown.min())

    return BacktestResult(
        tickers=req.tickers,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        final_value=round(final_value, 2),
        total_return=round(total_return, 4),
        annualized_return=round(annualized_return, 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown=round(max_drawdown, 4),
        equity_curve=equity_curve,
        trade_log=trade_log,
        timestamp=datetime.now(timezone.utc),
    )


@router.post("/run", response_model=BacktestResult)
async def run_backtest(body: BacktestRequest, auth: AuthDep):
    _, user = auth
    await check_rate_limit(user)

    try:
        return _run_backtest(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.error("Backtest failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Backtest failed")
