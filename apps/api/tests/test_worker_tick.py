"""Worker tick: verify the loop iterates the universe and calls the pipeline
once per symbol with the asset_class threaded through."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# The worker package lives at apps/worker (sibling to apps/api).
WORKER_PATH = Path(__file__).resolve().parents[3] / "worker"
sys.path.insert(0, str(WORKER_PATH.parent))


@pytest.fixture
def fake_signal():
    from ml.inference import SignalResult
    s = SignalResult("BUY", 0.7, 0.01)
    s.model_version = "v1.0"
    return s


def test_tick_iterates_universe(fake_signal, monkeypatch):
    monkeypatch.setenv("CRYPTO_UNIVERSE", "BTC-USD,ETH-USD,SOL-USD")

    from worker.main import tick_once

    calls: list[tuple[str, str, str]] = []

    def _stub(symbol, timeframe, asset_class):
        calls.append((symbol, timeframe, asset_class))
        return fake_signal

    with patch("worker.main.run_signal_pipeline", side_effect=_stub):
        # Crypto market is always open
        asyncio.run(tick_once("crypto"))

    symbols = sorted(c[0] for c in calls)
    assert symbols == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert all(c[2] == "crypto" for c in calls)
    assert all(c[1] == "5m" for c in calls)


def test_tick_skips_when_market_closed():
    """Equity adapter's is_market_open returns False on weekends — verify the
    tick short-circuits without calling the pipeline."""
    from worker.main import tick_once

    with patch("markets.equity.EquityAdapter.is_market_open", return_value=False), \
         patch("worker.main.run_signal_pipeline") as p:
        asyncio.run(tick_once("equity"))

    p.assert_not_called()
