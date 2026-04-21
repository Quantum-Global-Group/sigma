"""
PennyLane QAOA circuits for portfolio optimization.

The QAOA ansatz alternates between:
  - Cost unitary U_C(gamma) — encodes the objective (QUBO)
  - Mixer unitary U_M(beta) — drives transitions between basis states

For portfolio optimization, the cost Hamiltonian is built directly from the
QUBO matrix via Pauli Z operators. The mixer is the standard X-mixer.
"""

from __future__ import annotations

import numpy as np

try:
    import pennylane as qml  # type: ignore
    PENNYLANE_AVAILABLE = True
except ImportError:
    PENNYLANE_AVAILABLE = False

from config import settings


def _get_device(n_assets: int):
    """Return a PennyLane device — IBM backend if token set, else simulator."""
    if not PENNYLANE_AVAILABLE:
        raise ImportError("PennyLane is not installed")
    if settings.ibm_quantum_token:
        try:
            return qml.device(
                "qiskit.ibmq",
                wires=n_assets,
                backend=settings.ibm_quantum_backend if hasattr(settings, "ibm_quantum_backend") else "ibm_brisbane",
                ibmqx_token=settings.ibm_quantum_token,
            )
        except Exception:
            return qml.device("default.qubit", wires=n_assets)
    return qml.device("default.qubit", wires=n_assets)


def cost_hamiltonian(Q: np.ndarray):
    """Build a cost Hamiltonian from QUBO matrix Q via Z-Pauli expansion.

    For x in {0,1}^n with x_i = (1 - z_i) / 2 where z_i in {-1,+1}:
      x^T Q x = sum_i Q_ii (1-z_i)/2 + sum_{i<j} Q_ij (1-z_i)(1-z_j)/4

    Returns a qml.Hamiltonian (constant terms dropped — they don't affect optimization).
    """
    if not PENNYLANE_AVAILABLE:
        raise ImportError("PennyLane is not installed")
    n = Q.shape[0]
    coeffs: list[float] = []
    obs: list = []

    for i in range(n):
        # Linear: Q_ii * (1 - z_i)/2  → -Q_ii/2 * Z_i  (constant dropped)
        coeffs.append(-Q[i, i] / 2.0)
        obs.append(qml.PauliZ(i))

    for i in range(n):
        for j in range(i + 1, n):
            qij = Q[i, j] + Q[j, i]
            if abs(qij) < 1e-12:
                continue
            # (1-z_i)(1-z_j)/4 → 1/4 - z_i/4 - z_j/4 + z_i z_j /4
            coeffs.append(-qij / 4.0)
            obs.append(qml.PauliZ(i))
            coeffs.append(-qij / 4.0)
            obs.append(qml.PauliZ(j))
            coeffs.append(qij / 4.0)
            obs.append(qml.PauliZ(i) @ qml.PauliZ(j))

    return qml.Hamiltonian(coeffs, obs)


def build_qaoa_circuit(Q: np.ndarray, depth: int = 2):
    """Construct a QAOA QNode for the given QUBO matrix.

    Returns a tuple (qnode, n_assets). The QNode takes parameters of shape
    (2, depth): [gammas, betas] and returns the expectation value of the cost
    Hamiltonian.
    """
    if not PENNYLANE_AVAILABLE:
        raise ImportError("PennyLane is not installed")

    n_assets = Q.shape[0]
    dev = _get_device(n_assets)
    H_cost = cost_hamiltonian(Q)
    mixer_wires = list(range(n_assets))

    @qml.qnode(dev)
    def circuit(params):
        # Initial state: uniform superposition
        for w in mixer_wires:
            qml.Hadamard(wires=w)

        gammas, betas = params[0], params[1]
        for layer in range(depth):
            qml.templates.ApproxTimeEvolution(H_cost, gammas[layer], 1)
            for w in mixer_wires:
                qml.RX(2 * betas[layer], wires=w)

        return qml.expval(H_cost)

    return circuit, n_assets


def sample_qaoa_solution(Q: np.ndarray, params: np.ndarray, depth: int = 2, shots: int = 1024) -> np.ndarray:
    """After optimizing QAOA params, sample to get the most-probable bitstring."""
    if not PENNYLANE_AVAILABLE:
        raise ImportError("PennyLane is not installed")
    n_assets = Q.shape[0]
    dev = qml.device("default.qubit", wires=n_assets, shots=shots)
    H_cost = cost_hamiltonian(Q)
    mixer_wires = list(range(n_assets))

    @qml.qnode(dev)
    def sample_circuit(params):
        for w in mixer_wires:
            qml.Hadamard(wires=w)
        gammas, betas = params[0], params[1]
        for layer in range(depth):
            qml.templates.ApproxTimeEvolution(H_cost, gammas[layer], 1)
            for w in mixer_wires:
                qml.RX(2 * betas[layer], wires=w)
        return [qml.sample(qml.PauliZ(w)) for w in mixer_wires]

    samples = sample_circuit(params)
    samples = np.array(samples)  # shape (n_assets, shots)
    bitstrings = ((1 - samples) // 2).T  # shape (shots, n_assets)
    counts: dict[tuple, int] = {}
    for row in bitstrings:
        key = tuple(int(b) for b in row)
        counts[key] = counts.get(key, 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1])[0]
    return np.array(best, dtype=int)
