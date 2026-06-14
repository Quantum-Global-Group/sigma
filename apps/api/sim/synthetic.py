"""Synthetic market-data providers for offline, no-credentials full runs.

Lets the whole worker loop trade across every asset class without network or
broker accounts: deterministic OHLCV adapters (equity/crypto/forex + option
underlying) and a synthetic OptionDataProvider (chains/quotes/Greeks).

`install_synthetic_providers()` swaps them into `markets._REGISTRY` and points the
option provider at the synthetic chain (via OPTION_DATA_PROVIDER). It *keeps real
OANDA for forex when a token is configured*, so a full run uses live forex data
when you supply credentials and falls back to synthetic otherwise.

Enabled in the worker by `SYNTHETIC_DATA=true`; also reused by scripts/e2e_smoke.py.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from config import settings
from markets.base import MarketAdapter
from markets.options import OptionContract, OptionQuote

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OHLCV adapters
# ---------------------------------------------------------------------------

def _series(n: int, start: float, end: float, *, freq: str, wobble: float = 0.5,
            seed_key: str = "") -> pd.DataFrame:
    """Deterministic OHLCV with a gentle trend + noise, indexed to ~now."""
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq=freq, tz="UTC")
    n = len(idx)   # business-day freq can yield n∓1 on some date boundaries — match it
    rng = np.random.default_rng(abs(hash(seed_key)) % (2**32))
    close = np.linspace(start, end, n) + np.sin(np.arange(n) / 5.0) * wobble + rng.normal(0, wobble / 3, n)
    close = np.maximum(close, 0.01)
    return pd.DataFrame({
        "open": close * 0.999, "high": close * 1.004, "low": close * 0.996,
        "close": close, "volume": rng.uniform(1e6, 2e6, n),
    }, index=idx)


class _AlwaysOpenAdapter(MarketAdapter):
    """Base for synthetic adapters — always 'open' so the loop ticks any time."""

    def is_market_open(self, ts: datetime | None = None) -> bool:
        return True

    def normalize_symbol(self, symbol: str) -> str:
        return symbol.upper()


class SyntheticEquityAdapter(_AlwaysOpenAdapter):
    asset_class = "equity"

    def fetch_ohlcv(self, symbol: str, timeframe: str = "daily") -> pd.DataFrame:
        return _series(160, 100.0, 160.0, freq="B", seed_key=f"eq:{symbol}")


class SyntheticCryptoAdapter(_AlwaysOpenAdapter):
    asset_class = "crypto"

    def fetch_ohlcv(self, symbol: str, timeframe: str = "5m") -> pd.DataFrame:
        return _series(300, 40_000.0, 46_000.0, freq="5min", wobble=300.0, seed_key=f"cx:{symbol}")

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("/", "-")
        return s if "-" in s else f"{s}-USD"


class SyntheticForexAdapter(_AlwaysOpenAdapter):
    asset_class = "forex"

    def fetch_ohlcv(self, symbol: str, timeframe: str = "4h") -> pd.DataFrame:
        return _series(120, 1.08, 1.12, freq="4h", wobble=0.004, seed_key=f"fx:{symbol}")

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("/", "_").replace("-", "_")
        if "_" not in s and len(s) == 6:
            s = f"{s[:3]}_{s[3:]}"
        return s


class SyntheticOptionUnderlyingAdapter(_AlwaysOpenAdapter):
    """Underlying OHLCV for the option asset class — a *steep* uptrend so the
    directional signal clears the 'strong' threshold and the options worker picks
    a structure (otherwise it correctly HOLDs and only writes an audit record)."""
    asset_class = "option"

    def fetch_ohlcv(self, symbol: str, timeframe: str = "daily") -> pd.DataFrame:
        return _series(160, 100.0, 280.0, freq="B", wobble=0.3, seed_key=f"opt:{symbol}")


# ---------------------------------------------------------------------------
# Option data provider (chains / quotes / Greeks)
# ---------------------------------------------------------------------------

class SyntheticOptionData:
    """OptionDataProvider with liquid synthetic chains around a fixed spot, so the
    options worker's gates pass and it can place a paper structure offline."""

    def __init__(self, spot: float = 150.0) -> None:
        self.spot = spot

    def list_expiries(self, underlying: str) -> list[date]:
        today = date.today()
        return [today + timedelta(days=d) for d in (21, 35, 49)]

    def get_chain(self, underlying: str, expiry: date) -> list[OptionContract]:
        und = underlying.split(".")[-1]
        out: list[OptionContract] = []
        for i in range(-3, 4):
            strike = round(self.spot * (1 + 0.05 * i), 2)
            for right in ("call", "put"):
                cp = "C" if right == "call" else "P"
                code = f"US.{und}{expiry:%y%m%d}{cp}{int(strike * 1000):08d}"
                out.append(OptionContract(underlying=und, expiry=expiry, strike=strike,
                                          right=right, code=code))
        return out

    def get_quote(self, contract: OptionContract):
        qs = self.get_quotes([contract])
        return qs[0] if qs else None

    def get_quotes(self, contracts: list[OptionContract]) -> list[OptionQuote]:
        out: list[OptionQuote] = []
        for c in contracts:
            intrinsic = max(0.0, (self.spot - c.strike) if c.right == "call" else (c.strike - self.spot))
            mid = round(intrinsic + 2.5, 2)            # intrinsic + time value
            delta = 0.5 if c.right == "call" else -0.5
            out.append(OptionQuote(
                contract=c, bid=round(mid - 0.05, 2), ask=round(mid + 0.05, 2), last=mid,
                volume=1000, open_interest=5000, implied_vol=0.30,
                delta=delta, gamma=0.03, theta=-0.05, vega=0.15,
                ts=datetime.now(timezone.utc),
            ))
        return out


# ---------------------------------------------------------------------------
# demo signal combiner (opt-in: makes trades flow so the pipeline is watchable)
# ---------------------------------------------------------------------------

class DemoCombiner:
    """A demo signal source for watchable full runs — NOT a real strategy.

    Reads the recent trend of the synthetic bars and emits a confident directional
    signal so the data → signal → size → execute → persist → dashboard pipeline
    actually moves (the real combiner correctly HOLDs on smooth synthetic data).
    Opt-in via settings.synthetic_demo_signals; never used on real data unless you
    explicitly enable it."""

    def combine_signals(self, symbol, features, px_now, model_predictions=None):
        from ml.strategies.base import Signal
        col = "c" if "c" in getattr(features, "columns", []) else "close"
        try:
            closes = features[col].astype(float)
            slope = float(closes.iloc[-1] - closes.iloc[-20]) / max(abs(float(closes.iloc[-20])), 1e-9)
        except Exception:
            slope = 0.01
        strength = 0.7 if slope >= 0 else -0.7      # well past the 'strong' threshold
        return Signal(strength=strength, confidence=0.7, method="demo",
                      metadata={"demo": True, "slope": round(slope, 4)})


def demo_combiner_if_enabled(asset_class, default_factory):
    """Return a DemoCombiner when synthetic demo signals are on, else the real one."""
    if settings.synthetic_demo_signals:
        return DemoCombiner()
    return default_factory(asset_class)


# ---------------------------------------------------------------------------
# installer
# ---------------------------------------------------------------------------

def install_synthetic_providers() -> list[str]:
    """Swap synthetic adapters into markets._REGISTRY + enable the synthetic option
    provider. Forex keeps the REAL OANDA adapter when OANDA_API_TOKEN is set (so a
    full run uses live forex when credentialed). Returns the classes made synthetic."""
    import markets

    installed = ["equity", "crypto", "option"]
    markets._REGISTRY["equity"] = SyntheticEquityAdapter()
    markets._REGISTRY["crypto"] = SyntheticCryptoAdapter()
    markets._REGISTRY["option"] = SyntheticOptionUnderlyingAdapter()
    os.environ["OPTION_DATA_PROVIDER"] = "synthetic"

    if settings.oanda_api_token:
        logger.info("[synthetic] OANDA token present — forex uses REAL practice data")
    else:
        markets._REGISTRY["forex"] = SyntheticForexAdapter()
        installed.append("forex")

    logger.info("[synthetic] installed synthetic providers for: %s", installed)
    return installed
