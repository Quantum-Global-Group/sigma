"""Fixed-dimension signal embeddings for pgvector similarity search (MVP).

Builds a normalized numeric vector from component_weights + signal metadata.
No GPU model required — suitable for nightly batch embedding of labeled rows.
"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np

EMBEDDING_DIM = 64


def _field(row: Any, name: str, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def build_embedding_vector(row: Any, *, strategy_slots: Sequence[str]) -> np.ndarray:
    """Map a signal_history row → fixed-length float vector."""
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float64)
    cw = _field(row, "component_weights") or {}

    # Global combined signal (dims 0–3)
    vec[0] = _clip(cw.get("strength", 0.0))
    vec[1] = _clip(cw.get("confidence", _field(row, "confidence", 0.0) or 0.0))
    pred = _field(row, "predicted_return")
    if pred is not None:
        vec[2] = _clip(float(pred), lo=-0.2, hi=0.2) * 5.0
    sig = _field(row, "signal")
    if sig == "BUY":
        vec[3] = 1.0
    elif sig == "SELL":
        vec[3] = -1.0

    # Per-strategy slots (dims 4–14)
    comp = cw.get("component_signals") or {}
    for i, name in enumerate(strategy_slots[:11]):
        if name in comp:
            vec[4 + i] = _clip(comp[name])

    # Outcome one-hot-ish (dims 15–17)
    outcome = _field(row, "outcome")
    if outcome == "win":
        vec[15] = 1.0
    elif outcome == "loss":
        vec[16] = 1.0
    elif outcome == "flat":
        vec[17] = 1.0
    realized = _field(row, "realized_return")
    if realized is not None:
        vec[18] = _clip(float(realized), lo=-0.2, hi=0.2) * 5.0

    # Hash spillover for unknown strategy keys (dims 19–31)
    for key, val in sorted(comp.items()):
        if key in strategy_slots:
            continue
        h = int(hashlib.md5(key.encode()).hexdigest(), 16) % 13
        vec[19 + h] += _clip(val) * 0.5

    # L2-normalize for cosine similarity
    norm = np.linalg.norm(vec)
    if norm > 1e-12:
        vec /= norm
    return vec


def _clip(x, lo: float = -1.0, hi: float = 1.0) -> float:
    try:
        return float(np.clip(float(x), lo, hi))
    except (TypeError, ValueError):
        return 0.0
