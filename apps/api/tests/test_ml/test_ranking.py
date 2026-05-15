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


def test_fit_from_ohlcv_multi_symbol_uses_shared_scaler():
    """Regression test for the multi-symbol training bug: the scaler must
    be fit on all symbols' features combined, not refit per symbol."""
    import numpy as np
    df_a = _synthetic_ohlcv(200, trend=0.0008)
    df_b = _synthetic_ohlcv(200, trend=-0.0003)

    model = RankingModel()
    model.fit_from_ohlcv([df_a, df_b])

    assert model.sequence_builder._fitted
    assert model._trained
    # Predicting on either source should produce a valid SignalResult.
    r_a = model.predict(df_a)
    r_b = model.predict(df_b)
    assert r_a.signal in ("BUY", "SELL", "HOLD")
    assert r_b.signal in ("BUY", "SELL", "HOLD")

    # The scaler's mean should reflect both distributions, not just the last
    # one trained on. With per-symbol refitting the bug, the scaler.mean_
    # would equal df_b's column means exactly.
    from ml.sequences import FEATURE_COLUMNS, FeatureEngineer
    fe = FeatureEngineer()
    feats_b = fe.compute(df_b).dropna(subset=FEATURE_COLUMNS)
    b_mean = np.asarray(feats_b[FEATURE_COLUMNS].mean().values, dtype=np.float64)
    s_mean = np.asarray(model.sequence_builder.scaler.mean_, dtype=np.float64)
    # Some columns will inevitably be close, but at least one feature mean
    # should differ materially from df_b alone (proving the scaler saw both).
    assert np.linalg.norm(s_mean - b_mean) > 1e-6


def test_fit_from_ohlcv_skips_short_frames():
    """Short frames (less than ranking_window bars) should be silently dropped."""
    short = _synthetic_ohlcv(10)
    long = _synthetic_ohlcv(200)

    model = RankingModel()
    model.fit_from_ohlcv([short, long])
    assert model._trained


def test_fit_from_ohlcv_handles_empty_input():
    """No frames -> early return, no exception."""
    model = RankingModel()
    model.fit_from_ohlcv([])
    assert not model._trained
