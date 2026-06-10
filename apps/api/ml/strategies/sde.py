"""SDE (stochastic differential equation) strategies — physics-inspired.

Ported from tradeFlux core/sde_strategies.py. Three models + three strategies:
  - GeometricBrownianMotion -> GbmStrategy        (drift forecast)
  - OrnsteinUhlenbeck       -> OuMeanReversionStrategy (deviation from mean)
  - HestonModel             -> HestonVolStrategy   (vol-regime)

Each strategy estimates parameters on the trailing window and emits a single
graded Signal for the latest bar (the tradeFlux versions looped over all
bars; here we evaluate only the most recent)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from .base import BaseStrategy, Signal


# ---------------------------------------------------------------------------
# models (ported verbatim in spirit; only the bits the strategies use)
# ---------------------------------------------------------------------------

class GeometricBrownianMotion:
    def __init__(self, mu: float = 0.0, sigma: float = 0.2):
        self.mu = mu
        self.sigma = sigma

    def estimate_parameters(self, prices: pd.Series, dt: float = 1 / 252):
        rets = prices.pct_change().dropna()
        return rets.mean() / dt, rets.std() / np.sqrt(dt)

    def forecast(self, current_price: float, horizon: int, dt: float = 1 / 252) -> dict:
        T = horizon * dt
        mean = current_price * np.exp(self.mu * T)
        std = current_price * np.exp(self.mu * T) * np.sqrt(max(np.exp(self.sigma**2 * T) - 1, 0.0))
        z = norm.ppf(0.975)
        return {"mean": mean, "std": std, "lower_95": mean - z * std, "upper_95": mean + z * std}


class OrnsteinUhlenbeck:
    def __init__(self, theta: float = 0.1, mu: float = 0.0, sigma: float = 0.2):
        self.theta, self.mu, self.sigma = theta, mu, sigma

    def estimate_parameters(self, prices: pd.Series, dt: float = 1 / 252):
        log_prices = np.log(prices)
        rets = log_prices.diff().dropna()
        mu = log_prices.mean()
        X, Y = log_prices[:-1].values, log_prices[1:].values
        if len(X) > 1:
            corr = np.corrcoef(X, Y)[0, 1]
            theta = max(0.01, min(-np.log(corr) / dt, 10.0)) if corr > 0 else 0.1
        else:
            theta = 0.1
        return theta, mu, rets.std() / np.sqrt(dt)


class HestonModel:
    def __init__(self, mu=0.05, kappa=2.0, theta=0.04, sigma=0.3, rho=-0.7):
        self.mu, self.kappa, self.theta, self.sigma, self.rho = mu, kappa, theta, sigma, rho

    def estimate_parameters(self, prices: pd.Series, dt: float = 1 / 252) -> dict:
        rets = prices.pct_change().dropna()
        mu = rets.mean() / dt
        rolling_var = rets.rolling(window=20).var().dropna()
        if len(rolling_var) > 1:
            theta = rolling_var.mean()
            changes = rolling_var.diff().dropna()
            levels = rolling_var[:-1]
            kappa = max(0.1, min(-np.corrcoef(changes, levels)[0, 1] / dt, 10.0)) if (len(changes) and levels.std() > 0) else 2.0
            sigma = changes.std() / np.sqrt(dt) if changes.std() > 0 else 0.3
        else:
            theta, kappa, sigma = rets.var(), 2.0, 0.3
        return {"mu": mu, "kappa": kappa, "theta": theta, "sigma": sigma, "rho": -0.7}

    def forecast_volatility(self, current_variance: float, horizon: int, dt: float = 1 / 252) -> dict:
        T = horizon * dt
        mean_var = self.theta + (current_variance - self.theta) * np.exp(-self.kappa * T)
        return {"mean_volatility": float(np.sqrt(max(mean_var, 0.0)))}


# ---------------------------------------------------------------------------
# strategies
# ---------------------------------------------------------------------------

class GbmStrategy(BaseStrategy):
    def __init__(self, lookback_period: int = 60, forecast_horizon: int = 5) -> None:
        super().__init__("gbm")
        self.lookback_period = lookback_period
        self.forecast_horizon = forecast_horizon
        self.gbm = GeometricBrownianMotion()

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        close = features["c"]
        if len(close) < self.lookback_period or current_price <= 0:
            return Signal(0.0, 0.0, self.name)
        hist = close.iloc[-self.lookback_period:]
        self.gbm.mu, self.gbm.sigma = self.gbm.estimate_parameters(hist)
        fc = self.gbm.forecast(current_price, self.forecast_horizon)
        edge = (fc["mean"] - current_price) / current_price
        strength = float(np.clip(edge * 25.0, -1.0, 1.0))
        confidence = min(1.0, abs(edge) * 20.0)
        return Signal(strength, float(confidence), self.name,
                      metadata={"forecast_mean": fc["mean"], "edge": edge})


class OuMeanReversionStrategy(BaseStrategy):
    def __init__(self, lookback_period: int = 60, deviation_threshold: float = 0.02) -> None:
        super().__init__("ou")
        self.lookback_period = lookback_period
        self.deviation_threshold = deviation_threshold
        self.ou = OrnsteinUhlenbeck()

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        close = features["c"]
        if len(close) < self.lookback_period or current_price <= 0:
            return Signal(0.0, 0.0, self.name)
        hist = close.iloc[-self.lookback_period:]
        theta, mu, sigma = self.ou.estimate_parameters(hist)
        if mu == 0:
            return Signal(0.0, 0.0, self.name)
        deviation = (np.log(current_price) - mu) / mu
        # Mean reversion: below mean (negative deviation) → buy.
        strength = float(np.clip(-deviation / max(self.deviation_threshold, 1e-9), -1.0, 1.0))
        confidence = min(1.0, abs(deviation) / max(self.deviation_threshold, 1e-9) * 0.5)
        return Signal(strength, float(confidence), self.name,
                      metadata={"deviation": deviation, "theta": theta})


class HestonVolStrategy(BaseStrategy):
    def __init__(self, lookback_period: int = 60, volatility_threshold: float = 0.02) -> None:
        super().__init__("heston")
        self.lookback_period = lookback_period
        self.volatility_threshold = volatility_threshold
        self.heston = HestonModel()

    def generate_signal(self, symbol: str, features: pd.DataFrame, current_price: float) -> Signal:
        close = features["c"]
        if len(close) < self.lookback_period:
            return Signal(0.0, 0.0, self.name)
        hist = close.iloc[-self.lookback_period:]
        params = self.heston.estimate_parameters(hist)
        for k, v in params.items():
            setattr(self.heston, k, v)
        rets = hist.pct_change().dropna()
        # forecast_volatility returns a PER-BAR vol (it is built from rets.var()),
        # so annualize it to match hist_vol below. Without this, forecast_vol
        # (~0.01-0.02) was always far below the annualized hist_vol (~0.2-0.5),
        # making `ratio` strongly negative every bar and clipping strength to a
        # constant +1.0 — the source of the system-wide long-only bias (no SELLs).
        forecast_vol = (
            self.heston.forecast_volatility(rets.var(), horizon=5)["mean_volatility"]
            * np.sqrt(252)
        )
        hist_vol = rets.std() * np.sqrt(252)
        if hist_vol <= 0:
            return Signal(0.0, 0.0, self.name)
        ratio = (forecast_vol - hist_vol) / hist_vol
        # Falling vol regime → risk-on (+); rising vol → risk-off (−).
        strength = float(np.clip(-ratio / max(self.volatility_threshold, 1e-9), -1.0, 1.0))
        confidence = min(1.0, abs(ratio) / max(self.volatility_threshold, 1e-9) * 0.5)
        return Signal(strength, float(confidence), self.name,
                      metadata={"forecast_vol": forecast_vol, "hist_vol": hist_vol})
