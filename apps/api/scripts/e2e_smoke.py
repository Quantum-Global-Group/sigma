#!/usr/bin/env python
"""Offline, network-free end-to-end smoke test against a REAL Postgres + Redis.

Proves the full loop persists real rows — the thing mocked unit tests cannot:
  Phase 1  synthetic equity adapter → tick_once → signal_history + orders + positions
  Phase 2  seed backdated signals + candles → label_outcomes → evaluate_model
           → a model_evaluations row
  Phase 3  aggregate_pnl + snapshot_equity → an equity_snapshots row

No external market data or broker creds: a synthetic adapter is injected into
markets._REGISTRY and the paper executor fills deterministically. All writes use a
"SMOKE" symbol/version so `--clean` can wipe them.

Usage (with docker-compose Postgres+Redis up + migrations applied):
    DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sigma \
    PYTHONPATH=. python scripts/e2e_smoke.py [--clean]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# Safe offline defaults — must be set before importing config (pydantic reads env at import).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/sigma")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("EXECUTOR_MODE", "paper")
os.environ.setdefault("EQUITY_EXECUTOR", "paper")
os.environ.setdefault("MIN_SIGNAL_CONFIDENCE", "0")     # any non-HOLD signal trades
os.environ.setdefault("SENTIMENT_PROVIDER", "none")     # no FinBERT download
os.environ.setdefault("PERSIST_CANDLES", "true")
os.environ.setdefault("EQUITY_UNIVERSE", "SMOKE")
os.environ.setdefault("INTERNAL_SECRET", "dev-internal-secret")
os.environ.setdefault("SECRET_KEY", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # apps/api
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "worker"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from config import settings  # noqa: E402
from db.connection import AsyncSessionLocal  # noqa: E402
from db.models import (  # noqa: E402
    Candle, EquitySnapshot, ModelEvaluation, Order, Position, SignalHistory,
)

SYMBOL = "SMOKE"
SMOKE_VERSION = "smoke-v0"
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")


# ---------------------------------------------------------------------------
# synthetic data
# ---------------------------------------------------------------------------

def _uptrend(n: int = 160, end: datetime | None = None) -> pd.DataFrame:
    """A clean, steady uptrend so the combiner emits a confident BUY."""
    end = end or datetime.now(timezone.utc)
    idx = pd.date_range(end=end.date(), periods=n, freq="B", tz="UTC")
    close = np.linspace(100.0, 160.0, n) + np.sin(np.arange(n) / 5.0) * 0.5
    return pd.DataFrame({
        "open": close - 0.3, "high": close + 0.6, "low": close - 0.6,
        "close": close, "volume": np.full(n, 2_000_000.0),
    }, index=idx)


class _SyntheticEquityAdapter:
    asset_class = "equity"

    def fetch_ohlcv(self, symbol: str, timeframe: str = "daily") -> pd.DataFrame:
        return _uptrend()

    def is_market_open(self, ts=None) -> bool:
        return True

    def normalize_symbol(self, symbol: str) -> str:
        return symbol.upper()


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

async def _clean(session) -> None:
    await session.execute(delete(SignalHistory).where(SignalHistory.ticker == SYMBOL))
    await session.execute(delete(Order).where(Order.symbol == SYMBOL))
    await session.execute(delete(Position).where(Position.symbol == SYMBOL))
    await session.execute(delete(Candle).where(Candle.symbol == SYMBOL))
    await session.execute(delete(ModelEvaluation).where(ModelEvaluation.model_version == SMOKE_VERSION))
    await session.commit()
    print("  cleaned prior SMOKE rows")


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------

class _StubCombiner:
    """Forces a confident BUY so the order→position persistence path is exercised
    deterministically (the real combiner legitimately HOLDs on synthetic data — a
    strategy verdict, not a persistence concern)."""

    def combine_signals(self, symbol, features, px_now, model_predictions=None):
        from ml.strategies.base import Signal
        return Signal(strength=0.8, confidence=0.8, method="smoke", metadata={})


async def phase1_tick() -> None:
    print("\nPhase 1 — tick persistence (synthetic adapter, paper executor)")
    import markets
    import tick
    markets._REGISTRY["equity"] = _SyntheticEquityAdapter()   # inject — no network
    tick.build_default_combiner = lambda ac=None: _StubCombiner()   # force a tradeable BUY

    await tick.tick_once("equity", equity=10_000.0)

    async with AsyncSessionLocal() as s:
        n_sig = await s.scalar(select(func.count()).select_from(SignalHistory).where(SignalHistory.ticker == SYMBOL))
        n_ord = await s.scalar(select(func.count()).select_from(Order).where(Order.symbol == SYMBOL))
        n_pos = await s.scalar(select(func.count()).select_from(Position).where(Position.symbol == SYMBOL))
    record("signal_history persisted", (n_sig or 0) >= 1, f"{n_sig} rows")
    record("orders persisted", (n_ord or 0) >= 1, f"{n_ord} rows")
    record("positions persisted", (n_pos or 0) >= 1, f"{n_pos} rows")


async def phase2_self_evolve() -> None:
    print("\nPhase 2 — self-evolve chain (seed → label → evaluate)")
    from db.candle_store import upsert_candles
    from ml.evaluation import evaluate_model
    from ml.labeling import label_outcomes

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as s:
        # Backdated signals (labeling needs elapsed forward bars).
        for i in range(8):
            s.add(SignalHistory(
                user_id=settings.system_user_id, ticker=SYMBOL, timeframe="daily",
                asset_class="equity", signal="BUY", confidence=0.7,
                predicted_return=0.01, model_version=SMOKE_VERSION,
                created_at=now - timedelta(days=30 - i),
            ))
        # Candles spanning the window so the labeler finds entry + forward bars.
        idx = pd.date_range(end=now.date(), periods=45, freq="B", tz="UTC")
        close = np.linspace(100.0, 112.0, 45)
        df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                           "close": close, "volume": np.full(45, 1e6)}, index=idx)
        await upsert_candles(s, asset_class="equity", symbol=SYMBOL, timeframe="daily",
                             df=df, source="smoke", tail=1000)
        await s.commit()

    async with AsyncSessionLocal() as s:
        labeled = await label_outcomes(s, "equity", horizon_bars=5)
        await s.commit()
    record("label_outcomes labeled signals", labeled >= 1, f"{labeled} labeled")

    async with AsyncSessionLocal() as s:
        n_labeled = await s.scalar(
            select(func.count()).select_from(SignalHistory)
            .where(SignalHistory.model_version == SMOKE_VERSION)
            .where(SignalHistory.labeled_at.is_not(None))
        )
    record("outcomes written to signal_history", (n_labeled or 0) >= 1, f"{n_labeled} labeled rows")

    async with AsyncSessionLocal() as s:
        ev = await evaluate_model(s, "equity", SMOKE_VERSION)
        await s.commit()
        n_eval = await s.scalar(
            select(func.count()).select_from(ModelEvaluation)
            .where(ModelEvaluation.model_version == SMOKE_VERSION)
        )
    record("model_evaluations row written", (n_eval or 0) >= 1,
           f"n_samples={ev.n_samples}, dir_acc={ev.directional_accuracy}")


async def phase3_pnl() -> None:
    print("\nPhase 3 — portfolio P&L + equity snapshot")
    from risk.portfolio_pnl import aggregate_pnl, snapshot_equity

    async with AsyncSessionLocal() as s:
        positions = list((await s.execute(select(Position))).scalars().all())
        summary = aggregate_pnl(positions)
        record("aggregate_pnl computed", isinstance(summary.total_pnl, float),
               f"total_pnl={summary.total_pnl:.2f}, open={summary.open_positions}")

        await snapshot_equity(s, positions, base_equity=10_000.0)
        await s.commit()
        n_snap = await s.scalar(select(func.count()).select_from(EquitySnapshot))
    record("equity_snapshots row written", (n_snap or 0) >= 1, f"{n_snap} snapshots")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def _run(clean: bool) -> int:
    print("=== SIGMA end-to-end smoke (real Postgres + Redis) ===")
    print(f"DATABASE_URL = {settings.database_url}")
    if clean:
        async with AsyncSessionLocal() as s:
            await _clean(s)

    await phase1_tick()
    await phase2_self_evolve()
    await phase3_pnl()

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n=== {passed}/{total} checks passed ===")
    return 0 if passed == total else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="Delete prior SMOKE rows first")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.clean)))


if __name__ == "__main__":
    main()
