"""MLflow experiment-wrapper + forex registry tests (PR-C).

Designed to pass whether or not MLflow is installed: the wrapper degrades to a
no-op when MLflow is absent, and the real-logging path (when present) is pointed
at a temp file store so it never pollutes the repo or needs a server.
"""

from __future__ import annotations

import importlib.util

import pytest


_HAS_MLFLOW = importlib.util.find_spec("mlflow") is not None


# ---------------------------------------------------------------------------
# wrapper: no-op safety (always)
# ---------------------------------------------------------------------------

def test_run_noop_methods_never_raise():
    from ml.experiment import _Run
    run = _Run(None)
    run.log_params({"a": 1})
    run.log_metrics({"acc": 0.9})
    run.log_artifact("/nonexistent/path.pkl")
    run.set_tags({"k": "v"})  # must all be silent no-ops


def test_is_enabled_matches_mlflow_availability(monkeypatch):
    import ml.experiment as exp
    exp.reset_for_tests()
    assert exp.is_enabled() == _HAS_MLFLOW
    exp.reset_for_tests()


def test_start_run_yields_usable_run(tmp_path, monkeypatch):
    """Whether MLflow is present (logs to a temp file store) or absent (no-op),
    the run object's methods must never raise."""
    import ml.experiment as exp
    monkeypatch.setattr("config.settings.mlflow_tracking_uri", f"file://{tmp_path}/mlruns")
    monkeypatch.setattr("config.settings.mlflow_experiment", "sigma-test")
    exp.reset_for_tests()
    try:
        with exp.start_run("unit-test-run", tags={"asset_class": "forex"}) as run:
            run.log_params({"model_type": "ensemble", "version": "vtest"})
            run.log_metrics({"val_accuracy": 0.61, "n_train": 100})
    finally:
        exp.reset_for_tests()


@pytest.mark.skipif(not _HAS_MLFLOW, reason="mlflow not installed")
def test_start_run_records_to_store(tmp_path, monkeypatch):
    """When MLflow is installed, a run is actually persisted to the temp store."""
    import mlflow
    import ml.experiment as exp
    uri = f"file://{tmp_path}/mlruns"
    monkeypatch.setattr("config.settings.mlflow_tracking_uri", uri)
    monkeypatch.setattr("config.settings.mlflow_experiment", "sigma-test")
    exp.reset_for_tests()
    try:
        with exp.start_run("recorded-run", tags={"asset_class": "forex"}) as run:
            run.log_metrics({"val_accuracy": 0.55})
        client = mlflow.tracking.MlflowClient(tracking_uri=uri)
        expt = client.get_experiment_by_name("sigma-test")
        assert expt is not None
        runs = client.search_runs([expt.experiment_id])
        assert len(runs) >= 1
    finally:
        exp.reset_for_tests()


# ---------------------------------------------------------------------------
# registry: forex entry
# ---------------------------------------------------------------------------

def test_registry_has_forex_order():
    from ml.models.registry import _DEFAULT_ORDER
    assert "forex" in _DEFAULT_ORDER
    assert _DEFAULT_ORDER["forex"][0] == "ensemble"


def test_resolve_forex_returns_none_without_artifact(tmp_path, monkeypatch):
    """No forex artifact on disk → resolve() degrades to None (heuristic fallback)."""
    from ml.models import registry
    monkeypatch.setattr("config.settings.model_dir", str(tmp_path))
    registry.clear_cache()
    assert registry.resolve("forex") is None
    registry.clear_cache()
