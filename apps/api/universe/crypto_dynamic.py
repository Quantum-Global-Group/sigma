"""Dynamic crypto universe — rank candidate pairs by volatility × liquidity.

razorBill exposed config knobs for this (universe_top_n, min_quote_volume_24h,
score_w_*) but didn't ship an implementation. This is a sigma-side filling
of that gap: takes the configured candidate list (CRYPTO_UNIVERSE env var),
fetches a recent candle window for each, scores by realized-volatility ×
log(quote_volume), and returns the top N.

Refresh cadence is implicit — the worker calls `select()` every tick. To
avoid hammering the public API, results are cached for `universe_refresh_min`
minutes."""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass

import numpy as np

from markets.crypto import CoinbaseAdapter

from .base import UniverseSelector

logger = logging.getLogger(__name__)


@dataclass
class _Cached:
    expires_at: float
    symbols: list[str]


class DynamicCryptoUniverse(UniverseSelector):
    asset_class = "crypto"

    def __init__(
        self,
        candidates: list[str] | None = None,
        top_n: int | None = None,
        refresh_min: int | None = None,
    ) -> None:
        if candidates is None:
            raw = os.getenv(
                "CRYPTO_UNIVERSE",
                "BTC-USD,ETH-USD,SOL-USD,LINK-USD,AVAX-USD,DOGE-USD,MATIC-USD,ATOM-USD",
            )
            candidates = [s.strip().upper() for s in raw.split(",") if s.strip()]
        self._candidates = candidates
        self._top_n = top_n if top_n is not None else int(os.getenv("UNIVERSE_TOP_N", "6"))
        self._refresh_seconds = (refresh_min if refresh_min is not None else int(os.getenv("UNIVERSE_REFRESH_MIN", "30"))) * 60
        self._adapter = CoinbaseAdapter()
        self._cache: _Cached | None = None

    def select(self) -> list[str]:
        now = time.time()
        if self._cache and self._cache.expires_at > now:
            return self._cache.symbols

        ranked = self._rank()
        symbols = [s for s, _ in ranked[: self._top_n]]
        if not symbols:  # graceful fallback if every fetch failed
            symbols = self._candidates[: self._top_n]

        self._cache = _Cached(expires_at=now + self._refresh_seconds, symbols=symbols)
        logger.info("dynamic crypto universe -> %s", symbols)
        return symbols

    # ---- internal -------------------------------------------------------

    def _rank(self) -> list[tuple[str, float]]:
        scored: list[tuple[str, float]] = []
        for sym in self._candidates:
            try:
                df = self._adapter.fetch_ohlcv(sym, "5m")
            except Exception:
                logger.warning("universe rank: skip %s (fetch failed)", sym, exc_info=False)
                continue
            if df.empty or len(df) < 20:
                continue

            rets = np.log(df["close"] / df["close"].shift(1)).dropna()
            vol = float(rets.std()) if len(rets) > 1 else 0.0
            quote_vol = float((df["volume"] * df["close"]).sum())
            score = vol * math.log1p(max(quote_vol, 0.0))
            scored.append((sym, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
