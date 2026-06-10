"""Tests for tick audit provenance helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_api = Path(__file__).parents[1]
_worker = _api.parent / "worker"
sys.path.insert(0, str(_api))
sys.path.insert(0, str(_worker))

import pandas as np
import pandas as pd
import pytest

from risk.audit_log import AuditLog
from tick import _snapshot_audit_features


def test_snapshot_audit_features_last_bar():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    feats = pd.DataFrame(
        {"c": [100.0, 101.0, 102.0], "rsi": [40.0, 45.0, 50.0], "mom_1": [0.01, 0.02, 0.03]},
        index=idx,
    )
    snap = _snapshot_audit_features(feats)
    assert snap["px"] == pytest.approx(102.0)
    assert snap["rsi"] == pytest.approx(50.0)
    assert snap["mom_1"] == pytest.approx(0.03)


def test_snapshot_audit_features_empty():
    assert _snapshot_audit_features(pd.DataFrame()) == {}


def test_audit_log_gate_chain():
    log = AuditLog()
    rec = log.new("AAPL", asset_class="equity")
    rec.gate("G1_data", True)
    rec.gate("G2_signal", False, ["HOLD signal"]).finalize("skipped")
    assert rec.decision == "skipped"
    assert not rec.all_gates_passed
    d = rec.to_dict()
    assert d["asset_class"] == "equity"
    assert d["gates"][-1]["gate"] == "G2_signal"
