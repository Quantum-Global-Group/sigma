"""
Tests for the optional Langfuse tracing integration in ml/pipeline.py.

The default test configuration leaves LANGFUSE_* unset so the pipeline runs
with no-op spans and zero network calls. The "enabled" tests patch the
Langfuse client to a MagicMock and verify the expected span calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from ml import langfuse_tracing
from ml.pipeline import run_signal_pipeline


def _make_ohlcv(n: int = 80) -> pd.DataFrame:
    np.random.seed(42)
    close = 150 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame(
        {
            "close": close,
            "high": close + np.abs(np.random.randn(n)),
            "low": close - np.abs(np.random.randn(n)),
            "open": close,
            "volume": np.random.randint(1_000_000, 5_000_000, n).astype(float),
        }
    )


class TestDisabled:
    def setup_method(self) -> None:
        langfuse_tracing.reset_for_tests()

    def test_is_disabled_without_keys(self):
        with patch.object(langfuse_tracing.settings, "langfuse_public_key", ""), \
             patch.object(langfuse_tracing.settings, "langfuse_secret_key", ""):
            assert langfuse_tracing.is_enabled() is False
            assert langfuse_tracing.get_client() is None

    def test_pipeline_runs_with_noop_spans(self):
        with patch.object(langfuse_tracing.settings, "langfuse_public_key", ""), \
             patch.object(langfuse_tracing.settings, "langfuse_secret_key", ""), \
             patch("markets.equity.EquityAdapter.fetch_ohlcv", return_value=_make_ohlcv()):
            result = run_signal_pipeline("AAPL", "daily")
        assert result.signal in ("BUY", "SELL", "HOLD")

    def test_flush_is_safe_when_disabled(self):
        langfuse_tracing.flush()


class TestEnabled:
    def setup_method(self) -> None:
        langfuse_tracing.reset_for_tests()

    def teardown_method(self) -> None:
        langfuse_tracing.reset_for_tests()

    def _mock_client(self) -> MagicMock:
        client = MagicMock()
        client.start_as_current_observation.return_value.__enter__.return_value = MagicMock()
        client.start_as_current_observation.return_value.__exit__.return_value = False
        return client

    def test_pipeline_calls_langfuse_when_enabled(self):
        client = self._mock_client()
        with patch.object(langfuse_tracing.settings, "langfuse_public_key", "pk_test"), \
             patch.object(langfuse_tracing.settings, "langfuse_secret_key", "sk_test"), \
             patch.object(langfuse_tracing, "_client", client), \
             patch.object(langfuse_tracing, "_init_attempted", True), \
             patch("markets.equity.EquityAdapter.fetch_ohlcv", return_value=_make_ohlcv()):
            result = run_signal_pipeline("AAPL", "daily")

        assert result.signal in ("BUY", "SELL", "HOLD")
        # One root span + three child spans = four observations.
        assert client.start_as_current_observation.call_count == 4
        names = [
            kwargs.get("name")
            for _, kwargs in client.start_as_current_observation.call_args_list
        ]
        assert names == ["signal_pipeline", "fetch_ohlcv", "build_features", "predict"]

    def test_flush_invokes_client_flush(self):
        client = self._mock_client()
        with patch.object(langfuse_tracing.settings, "langfuse_public_key", "pk_test"), \
             patch.object(langfuse_tracing.settings, "langfuse_secret_key", "sk_test"), \
             patch.object(langfuse_tracing, "_client", client), \
             patch.object(langfuse_tracing, "_init_attempted", True):
            langfuse_tracing.flush()
        client.flush.assert_called_once()

    def test_pipeline_records_error_on_failure(self):
        client = self._mock_client()
        root_span = MagicMock()
        client.start_as_current_observation.return_value.__enter__.return_value = root_span

        with patch.object(langfuse_tracing.settings, "langfuse_public_key", "pk_test"), \
             patch.object(langfuse_tracing.settings, "langfuse_secret_key", "sk_test"), \
             patch.object(langfuse_tracing, "_client", client), \
             patch.object(langfuse_tracing, "_init_attempted", True), \
             patch("markets.equity.EquityAdapter.fetch_ohlcv", side_effect=ValueError("bad ticker")):
            try:
                run_signal_pipeline("XXXX", "daily")
            except ValueError:
                pass

        # The error update should have been called at least once with level=ERROR.
        error_updates = [
            call for call in root_span.update.call_args_list
            if call.kwargs.get("level") == "ERROR"
        ]
        assert error_updates, "expected at least one error update on a span"
