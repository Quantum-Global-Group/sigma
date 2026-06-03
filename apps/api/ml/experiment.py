"""Optional MLflow experiment tracking for *training* runs.

Langfuse (ml/langfuse_tracing.py) traces inference; this is its training-side
counterpart. When MLflow is importable it logs params/metrics/artifacts to the
configured tracking store (empty `mlflow_tracking_uri` → MLflow's local
`./mlruns` file store, no server needed). When MLflow is absent or
mis-configured, every helper degrades to a no-op so training never hard-depends
on it — the same philosophy as the Langfuse wrapper.

Experiment names are formalized per model family, e.g. `sigma-equity-ensemble`,
`sigma-crypto-ranking`. Pass `tags={"asset_class": "...", "model_type": "..."}`
to `start_run` to select the experiment automatically.

Usage:
    from ml.experiment import start_run
    with start_run("train-ensemble-equity-v1.0", tags={"asset_class": "equity", "model_type": "ensemble"}) as run:
        run.log_params({...}); run.log_metrics({...}); run.log_artifact(path)
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from config import settings

logger = logging.getLogger(__name__)

_mlflow: Any | None = None
_init_attempted = False
_active_experiment: str | None = None

# Formal experiment names per (asset_class, model_type).
_EXPERIMENT_NAMES: dict[tuple[str, str], str] = {
    ("equity", "ensemble"): "sigma-equity-ensemble",
    ("equity", "lstm"): "sigma-equity-lstm",
    ("equity", "quantum_hybrid"): "sigma-equity-quantum-hybrid",
    ("crypto", "ranking"): "sigma-crypto-ranking",
    ("crypto", "ensemble"): "sigma-crypto-ensemble",
    ("forex", "ensemble"): "sigma-forex-ensemble",
    ("forex", "lstm"): "sigma-forex-lstm",
    ("forex", "quantum_hybrid"): "sigma-forex-quantum-hybrid",
}


def resolve_experiment_name(asset_class: str, model_type: str) -> str:
    """Map (asset_class, model_type) → MLflow experiment name."""
    ac = (asset_class or "equity").lower()
    mt = (model_type or "ensemble").lower().replace("-", "_")
    return _EXPERIMENT_NAMES.get((ac, mt), f"sigma-{ac}-{mt.replace('_', '-')}")


def _experiment_from_tags(tags: Optional[dict]) -> str:
    if tags:
        ac = tags.get("asset_class")
        mt = tags.get("model_type")
        if ac and mt:
            return resolve_experiment_name(str(ac), str(mt))
    return settings.mlflow_experiment or "sigma-training"


def _load_mlflow() -> Any | None:
    """Lazy singleton MLflow handle, configured to the settings store. None on failure."""
    global _mlflow, _init_attempted
    if _init_attempted:
        return _mlflow
    _init_attempted = True
    try:
        if not settings.mlflow_tracking_uri or settings.mlflow_tracking_uri.startswith("file://"):
            os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

        import mlflow  # type: ignore[import-not-found]

        if settings.mlflow_tracking_uri:
            mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        _mlflow = mlflow
        logger.info(
            "MLflow tracking enabled (uri=%s)",
            settings.mlflow_tracking_uri or "local ./mlruns",
        )
    except Exception as exc:
        logger.warning("MLflow unavailable — experiment logging disabled: %s", exc)
        _mlflow = None
    return _mlflow


def _set_experiment(mlflow: Any, name: str) -> None:
    global _active_experiment
    if _active_experiment == name:
        return
    mlflow.set_experiment(name)
    _active_experiment = name


def is_enabled() -> bool:
    return _load_mlflow() is not None


class _Run:
    """Wraps an active MLflow run; every method swallows logging errors so a
    tracking hiccup never aborts a training job. A None client → pure no-op."""

    def __init__(self, mlflow: Any | None) -> None:
        self._mlflow = mlflow

    def log_params(self, params: dict) -> None:
        if self._mlflow is None:
            return
        try:
            self._mlflow.log_params(params)
        except Exception:
            logger.debug("mlflow log_params failed", exc_info=True)

    def log_metrics(self, metrics: dict) -> None:
        if self._mlflow is None:
            return
        try:
            self._mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v is not None})
        except Exception:
            logger.debug("mlflow log_metrics failed", exc_info=True)

    def log_artifact(self, path: str) -> None:
        if self._mlflow is None:
            return
        try:
            self._mlflow.log_artifact(path)
        except Exception:
            logger.debug("mlflow log_artifact failed", exc_info=True)

    def set_tags(self, tags: dict) -> None:
        if self._mlflow is None:
            return
        try:
            self._mlflow.set_tags(tags)
        except Exception:
            logger.debug("mlflow set_tags failed", exc_info=True)


@contextmanager
def start_run(run_name: str, tags: Optional[dict] = None) -> Iterator[_Run]:
    """Context manager for one tracked training run. Yields a `_Run` (no-op when
    MLflow is disabled). Caller exceptions propagate (and mark the MLflow run
    failed); MLflow setup errors degrade to a no-op run."""
    mlflow = _load_mlflow()
    if mlflow is None:
        yield _Run(None)
        return
    try:
        _set_experiment(mlflow, _experiment_from_tags(tags))
        cm = mlflow.start_run(run_name=run_name)
    except Exception as exc:
        logger.warning("MLflow start_run failed (%s) — continuing untracked", exc)
        yield _Run(None)
        return
    with cm:
        run = _Run(mlflow)
        if tags:
            run.set_tags(tags)
        yield run


def reset_for_tests() -> None:
    """Test helper: clear the cached client so settings changes take effect."""
    global _mlflow, _init_attempted, _active_experiment
    _mlflow = None
    _init_attempted = False
    _active_experiment = None
