"""
Quantum-classical hybrid SVC.

Uses PennyLane to compute a quantum kernel matrix over PCA-reduced features,
then trains an SVC with `kernel="precomputed"`. Falls back to a classical RBF
SVC if PennyLane is unavailable, so the model always provides predictions.
"""

from __future__ import annotations

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.inference import SignalResult
from ml.models.base import BaseSignalModel, label_to_signal

logger = logging.getLogger(__name__)

N_QUBITS = 6   # PCA dimensions / qubits — keep small for simulator speed


def _quantum_kernel_available() -> bool:
    try:
        import pennylane  # noqa: F401
        return True
    except ImportError:
        return False


def _build_quantum_kernel(n_qubits: int):
    """Construct a ZZ-feature-map-style kernel function using PennyLane."""
    import pennylane as qml  # type: ignore

    dev = qml.device("default.qubit", wires=n_qubits)

    @qml.qnode(dev)
    def kernel_circuit(x1, x2):
        for i in range(n_qubits):
            qml.Hadamard(wires=i)
            qml.RZ(x1[i], wires=i)
        for i in range(n_qubits - 1):
            qml.CNOT(wires=[i, i + 1])
            qml.RZ(x1[i] * x1[i + 1], wires=i + 1)
            qml.CNOT(wires=[i, i + 1])
        # Adjoint feature map for x2
        for i in reversed(range(n_qubits - 1)):
            qml.CNOT(wires=[i, i + 1])
            qml.RZ(-x2[i] * x2[i + 1], wires=i + 1)
            qml.CNOT(wires=[i, i + 1])
        for i in range(n_qubits):
            qml.RZ(-x2[i], wires=i)
            qml.Hadamard(wires=i)
        return qml.probs(wires=range(n_qubits))

    def kernel(x1, x2):
        probs = kernel_circuit(x1, x2)
        return float(probs[0])  # |⟨0|U†(x2)U(x1)|0⟩|²

    return kernel


def _kernel_matrix(X1: np.ndarray, X2: np.ndarray, kernel_fn) -> np.ndarray:
    K = np.zeros((len(X1), len(X2)))
    for i, x1 in enumerate(X1):
        for j, x2 in enumerate(X2):
            K[i, j] = kernel_fn(x1, x2)
    return K


class QuantumHybridModel(BaseSignalModel):
    model_version = "quantum_hybrid_v1.0"

    def __init__(self, n_qubits: int = N_QUBITS):
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import SVC

        self.n_qubits = n_qubits
        self.scaler = StandardScaler()
        self.pca = PCA(n_components=n_qubits)
        self.svc: SVC | None = None
        self.X_train: np.ndarray | None = None
        self.feature_names: list[str] = []
        self.use_quantum = _quantum_kernel_available()
        self._fitted = False

    def _project(self, X: np.ndarray, fit: bool = False) -> np.ndarray:
        if fit:
            X = self.scaler.fit_transform(X)
            X = self.pca.fit_transform(X)
        else:
            X = self.scaler.transform(X)
            X = self.pca.transform(X)
        # Bound to [-π, π] for stable circuit angles
        return np.clip(X, -np.pi, np.pi)

    def train(self, X: pd.DataFrame, y: np.ndarray) -> None:
        from sklearn.svm import SVC

        self.feature_names = list(X.columns)
        X_proj = self._project(X.values, fit=True)
        self.X_train = X_proj

        if self.use_quantum:
            try:
                kernel_fn = _build_quantum_kernel(self.n_qubits)
                K_train = _kernel_matrix(X_proj, X_proj, kernel_fn)
                self.svc = SVC(kernel="precomputed", probability=True)
                self.svc.fit(K_train, y)
                logger.info("QuantumHybridModel trained with quantum kernel on %d samples", len(X))
                self._fitted = True
                return
            except Exception as exc:
                logger.warning("Quantum kernel training failed: %s — falling back to classical RBF", exc)
                self.use_quantum = False

        # Classical fallback
        self.svc = SVC(kernel="rbf", probability=True, gamma="scale")
        self.svc.fit(X_proj, y)
        logger.info("QuantumHybridModel trained with classical RBF kernel on %d samples", len(X))
        self._fitted = True

    def predict(self, features: pd.DataFrame) -> SignalResult:
        if not self._fitted or self.svc is None or features.empty:
            return SignalResult("HOLD", 0.5, 0.0)

        if self.feature_names:
            X = features[self.feature_names].iloc[[-1]].values
        else:
            X = features.iloc[[-1]].values

        X_proj = self._project(X)

        if self.use_quantum and self.X_train is not None:
            kernel_fn = _build_quantum_kernel(self.n_qubits)
            K = _kernel_matrix(X_proj, self.X_train, kernel_fn)
            proba = self.svc.predict_proba(K)[0]
        else:
            proba = self.svc.predict_proba(X_proj)[0]

        label = int(np.argmax(proba))
        confidence = float(proba[label])
        predicted_return = float((proba[2] - proba[0]) * 0.05)

        result = SignalResult(label_to_signal(label), round(confidence, 4), round(predicted_return, 6))
        result.model_version = self.model_version + ("_q" if self.use_quantum else "_c")
        return result

    def save(self, path: str) -> None:
        joblib.dump({
            "scaler": self.scaler,
            "pca": self.pca,
            "svc": self.svc,
            "X_train": self.X_train,
            "feature_names": self.feature_names,
            "use_quantum": self.use_quantum,
            "n_qubits": self.n_qubits,
            "model_version": self.model_version,
        }, path)

    @classmethod
    def load(cls, path: str) -> "QuantumHybridModel":
        data = joblib.load(path)
        instance = cls(n_qubits=data["n_qubits"])
        instance.scaler = data["scaler"]
        instance.pca = data["pca"]
        instance.svc = data["svc"]
        instance.X_train = data["X_train"]
        instance.feature_names = data["feature_names"]
        instance.use_quantum = data["use_quantum"] and _quantum_kernel_available()
        instance.model_version = data.get("model_version", "quantum_hybrid_v1.0")
        instance._fitted = True
        return instance
