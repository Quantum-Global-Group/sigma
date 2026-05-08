"""Tests for the razorBill-derived RankingModel adapter."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.inference import SignalResult
from ml.models.ranking import RankingModel
from ml.sequences import FEATURE_COLUMNS, FeatureEngineer, SequenceBuilder


def _synthetic_ohlcv(n: int = 200, trend: float = 0.0, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rets = rng.normal(trend, noise, n)
    closes = 100 * np.exp(np.cumsum(rets))
    highs = closes * (1 + rng.uniform(0, 0.002, n))
    lows = closes * (1 - rng.uniform(0, 0.002, n))
    opens = closes * (1 + rng.normal(0, 0.0005, n))
    vols = rng.uniform(1e6, 5e6, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols,
    }, index=idx)


def test_feature_engineer_emits_all_columns():
    df = _synthetic_ohlcv(120)
    feats = FeatureEngineer().compute(df)
    for col in FEATURE_COLUMNS:
        assert col in feats.columns, f"missing feature: {col}"


def test_sequence_builder_produces_fixed_window():
    df = _synthetic_ohlcv(200)
    feats = FeatureEngineer().compute(df)
    sb = SequenceBuilder(window=30)
    seqs = sb.fit_transform(feats, horizon=3)
    assert len(seqs) > 0
    assert seqs[0].X.shape == (30, len(FEATURE_COLUMNS))


def test_ranking_model_predicts_signal_result():
    df = _synthetic_ohlcv(200, trend=0.0005)
    model = RankingModel()
    model.fit_from_ohlcv(df)
    result = model.predict(df)
    assert isinstance(result, SignalResult)
    assert result.signal in ("BUY", "SELL", "HOLD")
    assert 0.0 <= result.confidence <= 1.0
    assert result.component_weights is not None
    assert "ranking" in result.component_weights


def test_ranking_model_holds_when_window_too_small():
    df = _synthetic_ohlcv(20)
    model = RankingModel()
    result = model.predict(df)
    assert result.signal == "HOLD"
    assert result.confidence == 0.5


def test_ranking_model_save_load_roundtrip(tmp_path):
    df = _synthetic_ohlcv(150)
    model = RankingModel()
    model.fit_from_ohlcv(df)

    path = tmp_path / "ranking.pkl"
    model.save(str(path))
    loaded = RankingModel.load(str(path))

    r1 = model.predict(df)
    r2 = loaded.predict(df)
    assert r1.signal == r2.signal
    assert abs(r1.predicted_return - r2.predicted_return) < 1e-6


def test_ranking_model_threshold_buckets(monkeypatch):
    """Force a high threshold and verify HOLD path."""
    from config import settings as cfg
    monkeypatch.setattr(cfg, "ranking_signal_threshold", 1.0)
    df = _synthetic_ohlcv(150, trend=0.0005)
    model = RankingModel()
    model.fit_from_ohlcv(df)
    result = model.predict(df)
    assert result.signal == "HOLD"
