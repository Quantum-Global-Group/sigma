"""
Extended pipeline unit tests — each step tested in isolation.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ml.features import build_features, _rsi, _atr
from ml.inference import SignalResult, predict
from ml.pipeline import run_signal_pipeline


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 80) -> pd.DataFrame:
    np.random.seed(42)
    close = 150 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    volume = np.random.randint(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"close": close, "high": high, "low": low, "open": close, "volume": volume})


def _make_features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rsi_14": [45.0],
            "roc_10": [0.02],
            "ema_20": [151.0],
            "ema_50": [149.0],
            "ema_ratio": [1.013],
            "bb_width": [0.04],
            "atr_14": [2.0],
            "volume_ratio": [1.1],
            "ret_1d": [0.005],
            "ret_5d": [0.03],
        }
    )


# ─── fetch_ohlcv ─────────────────────────────────────────────────────────────

class TestFetchOHLCV:
    """ml.data.fetch_ohlcv now delegates to the multi-source equity adapter.

    These pin the yfinance fallback provider and patch yfinance.download (the
    real call inside markets.equity_data.fetch_yfinance)."""

    def test_returns_dataframe(self, monkeypatch):
        monkeypatch.setattr("config.settings.equity_data_providers", "yfinance")
        mock_df = _make_ohlcv()
        with patch("yfinance.download", return_value=mock_df):
            from ml.data import fetch_ohlcv
            result = fetch_ohlcv("AAPL", "daily")
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_raises_when_all_providers_empty(self, monkeypatch):
        monkeypatch.setattr("config.settings.equity_data_providers", "yfinance")
        with patch("yfinance.download", return_value=pd.DataFrame()):
            from ml.data import fetch_ohlcv
            with pytest.raises(ValueError, match="No equity data"):
                fetch_ohlcv("XXXX", "daily")

    def test_column_normalisation(self, monkeypatch):
        monkeypatch.setattr("config.settings.equity_data_providers", "yfinance")
        df = _make_ohlcv()
        # yfinance sometimes returns MultiIndex — test that we flatten it
        df.columns = pd.MultiIndex.from_tuples([(c, "AAPL") for c in df.columns])
        with patch("yfinance.download", return_value=df):
            from ml.data import fetch_ohlcv
            result = fetch_ohlcv("AAPL", "daily")
        assert "close" in result.columns


# ─── build_features ──────────────────────────────────────────────────────────

class TestBuildFeatures:
    def test_all_expected_columns_present(self):
        df = _make_ohlcv()
        features = build_features(df)
        expected = {"rsi_14", "roc_10", "ema_20", "ema_50", "ema_ratio", "bb_width", "atr_14", "volume_ratio", "ret_1d", "ret_5d"}
        assert expected.issubset(set(features.columns))

    def test_no_nans_after_warmup(self):
        df = _make_ohlcv(80)
        features = build_features(df)
        assert not features.isnull().any().any()

    def test_rsi_bounded(self):
        df = _make_ohlcv(80)
        features = build_features(df)
        assert features["rsi_14"].between(0, 100).all()

    def test_ema_ratio_near_one_for_sideways(self):
        # A mean-reverting sideways series → EMA20 and EMA50 stay close.
        # Use tiny Gaussian noise so features don't all drop as NaN.
        np.random.seed(0)
        n = 80
        close = pd.Series(100.0 + np.random.randn(n) * 0.05)
        high = close + 0.1
        low = close - 0.1
        df = pd.DataFrame({"close": close, "high": high, "low": low, "open": close, "volume": [1e6] * n})
        features = build_features(df)
        assert not features.empty, "build_features returned empty DataFrame"
        # EMA ratio should be within 5% of 1.0 for sideways price
        assert abs(features["ema_ratio"].iat[-1] - 1.0) < 0.05


# ─── predict (inference) ─────────────────────────────────────────────────────

class TestPredict:
    def test_returns_signal_result(self):
        result = predict(_make_features())
        assert isinstance(result, SignalResult)
        assert result.signal in ("BUY", "SELL", "HOLD")
        assert 0.0 <= result.confidence <= 1.0

    def test_empty_features_returns_hold(self):
        result = predict(pd.DataFrame())
        assert result.signal == "HOLD"
        assert result.confidence == 0.5

    def test_oversold_rsi_biases_buy(self):
        # Force the heuristic path: with a trained ensemble committed under
        # saved_models/, resolve('equity') would otherwise classify these
        # hand-crafted features per the model weights, defeating the intent.
        features = pd.DataFrame([{"rsi_14": 20.0, "roc_10": 0.0, "ema_20": 100.0, "ema_50": 98.0, "ema_ratio": 1.02, "bb_width": 0.03, "atr_14": 1.0, "volume_ratio": 1.0, "ret_1d": 0.001, "ret_5d": 0.01}])
        with patch("ml.models.registry.resolve", return_value=None):
            result = predict(features)
        assert result.signal in ("BUY", "HOLD")

    def test_overbought_rsi_biases_sell(self):
        # Force the heuristic path: the registry may load a saved ensemble
        # model from saved_models/ which would classify these features however
        # the trained weights say, defeating the test's intent.
        features = pd.DataFrame([{"rsi_14": 85.0, "roc_10": 0.0, "ema_20": 98.0, "ema_50": 102.0, "ema_ratio": 0.96, "bb_width": 0.08, "atr_14": 2.0, "volume_ratio": 0.8, "ret_1d": -0.01, "ret_5d": -0.04}])
        with patch("ml.models.registry.resolve", return_value=None):
            result = predict(features)
        assert result.signal in ("SELL", "HOLD")


# ─── run_signal_pipeline ─────────────────────────────────────────────────────

class TestRunSignalPipeline:
    def test_end_to_end_mocked(self):
        # The pipeline uses MarketAdapter (markets/) rather than the raw
        # ml.data.fetch_ohlcv helper since the asset-class refactor; patch
        # the equity adapter's fetch_ohlcv at the class level so all
        # registry-acquired instances use the mock.
        mock_df = _make_ohlcv(80)
        with patch("markets.equity.EquityAdapter.fetch_ohlcv", return_value=mock_df):
            result = run_signal_pipeline("AAPL", "daily")
        assert result.signal in ("BUY", "SELL", "HOLD")

    def test_propagates_value_error_on_bad_ticker(self):
        with patch(
            "markets.equity.EquityAdapter.fetch_ohlcv",
            side_effect=ValueError("No data returned for ticker: XXXX"),
        ):
            with pytest.raises(ValueError, match="No data"):
                run_signal_pipeline("XXXX", "daily")
