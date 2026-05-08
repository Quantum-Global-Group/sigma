from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from .config import settings


def detect_regime(ema_fast: float, ema_slow: float, vol: float) -> str:
    if ema_fast > ema_slow and vol < 0.05:
        return "bull"
    if ema_fast < ema_slow and vol > 0.05:
        return "bear"
    return "neutral"


def fuse_signal(model_score: float, regime_flag: float, sent_score: float) -> float:
    w = settings.strategy
    fused = w.weight_model * model_score + w.weight_regime * regime_flag + w.weight_sent * sent_score
    return float(np.clip(fused, -1.0, 1.0))


@dataclass
class RiskState:
    var_95: float
    max_drawdown: float
    atr: float


def apply_risk(signal: float, risk: RiskState) -> float:
    # scale down by VaR budget if needed
    budget = settings.strategy.risk_var_95
    if risk.var_95 > 1e-9:
        scale = min(1.0, budget / risk.var_95)
    else:
        scale = 1.0
    if risk.max_drawdown >= settings.strategy.risk_max_drawdown:
        scale = 0.0
    return float(np.clip(signal * scale, -1.0, 1.0))


@dataclass
class Sizing:
    qty: float


def size_position(equity: float, price: float, vol_target: float, signal: float) -> Sizing:
    if price <= 0 or vol_target <= 0:
        return Sizing(qty=0.0)
    kelly = min(settings.strategy.kelly_cap, 0.5 * abs(signal))
    notional = equity * kelly
    cap = float(settings.per_trade_notional_cap_usd)
    if cap > 0.0:
        notional = min(notional, cap)
    qty = notional / price
    return Sizing(qty=max(0.0, qty))