from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger


def compute_equity_curve(trades: pd.DataFrame, initial_equity: float) -> pd.DataFrame:
    """Compute equity curve from trades"""
    if trades.empty:
        return pd.DataFrame(columns=["t", "equity"])
    
    # Sort by time
    trades = trades.sort_values("t").reset_index(drop=True)
    
    # Calculate cumulative PnL
    trades["pnl"] = 0.0
    for i, row in trades.iterrows():
        if row["side"] == "buy":
            trades.loc[i, "pnl"] = -row["qty"] * row["px"] - row["fee"] - row["slip"]
        else:  # sell
            trades.loc[i, "pnl"] = row["qty"] * row["px"] - row["fee"] - row["slip"]
    
    trades["cumulative_pnl"] = trades["pnl"].cumsum()
    trades["equity"] = initial_equity + trades["cumulative_pnl"]
    
    # Create equity curve
    out = trades[["t", "equity"]].copy()
    out = out.drop_duplicates("t").sort_values("t")
    
    return out


def compute_metrics(trades: pd.DataFrame, equity_curve: pd.DataFrame) -> dict:
    if equity_curve.empty:
        return {"trades": 0, "return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "turnover": 0.0}
    eq = equity_curve["equity"].astype(float).values
    ret = (eq[-1] / eq[0] - 1.0) if len(eq) > 1 else 0.0
    roll_max = np.maximum.accumulate(eq)
    drawdowns = (roll_max - eq) / np.maximum(roll_max, 1e-9)
    # Drawdown duration: longest consecutive below peak
    duration = 0
    max_duration = 0
    peak = roll_max[0] if len(roll_max) else 0.0
    for v in eq:
        if v < peak:
            duration += 1
            max_duration = max(max_duration, duration)
        else:
            peak = max(peak, v)
            duration = 0
    max_dd = float(drawdowns.max()) if drawdowns.size else 0.0
    # Simple turnover: sum of notional traded over average equity (placeholder)
    turnover = 0.0
    if not trades.empty:
        tdf = trades.copy()
        tdf["notional"] = (tdf["qty"].astype(float) * tdf["px"].astype(float)).abs()
        turnover = float(tdf["notional"].sum() / max(np.mean(eq), 1e-9))
    # Sharpe/Sortino from periodic returns
    rets = np.diff(eq) / np.maximum(eq[:-1], 1e-9) if len(eq) > 1 else np.array([])
    if rets.size:
        sharpe = float(np.mean(rets) / (np.std(rets) + 1e-9) * np.sqrt(252))  # assuming daily-like
        downside = rets[rets < 0]
        sortino = float(np.mean(rets) / (np.std(downside) + 1e-9) * np.sqrt(252)) if downside.size else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0
    calmar = float(ret / (max_dd + 1e-9)) if max_dd > 0 else 0.0
    return {
        "trades": int(len(trades)),
        "return": float(ret),
        "max_drawdown": float(max_dd),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "calmar": float(calmar),
        "turnover": float(turnover),
        "max_dd_duration": int(max_duration),
    }


def daily_aggregate(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Aggregate equity curve to daily frequency"""
    if equity_curve.empty:
        return pd.DataFrame()
    
    # Ensure datetime index
    eq = equity_curve.copy()
    eq["t"] = pd.to_datetime(eq["t"])
    eq = eq.set_index("t")
    
    # Resample to daily
    daily = eq.resample("D").last().dropna()
    
    return daily.reset_index()