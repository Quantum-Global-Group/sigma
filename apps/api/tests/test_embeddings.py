"""Tests for fixed-dim signal embedding vectors."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from ml.embeddings import EMBEDDING_DIM, build_embedding_vector


def test_build_embedding_vector_normalized():
    row = SimpleNamespace(
        component_weights={
            "strength": 0.5,
            "confidence": 0.7,
            "component_signals": {"ict": 0.4, "momentum": -0.1},
        },
        confidence=0.7,
        predicted_return=0.02,
        signal="BUY",
        outcome="win",
        realized_return=0.015,
    )
    vec = build_embedding_vector(row, strategy_slots=("momentum", "ict"))
    assert vec.shape == (EMBEDDING_DIM,)
    assert np.linalg.norm(vec) == pytest.approx(1.0, rel=1e-5)


def test_build_embedding_vector_empty():
    row = SimpleNamespace(component_weights={}, confidence=0.0, signal="HOLD", outcome=None, realized_return=None)
    vec = build_embedding_vector(row, strategy_slots=())
    assert len(vec) == EMBEDDING_DIM
