"""
QUBO formulation for portfolio selection.

Given expected returns mu (n,) and covariance Sigma (n,n), the portfolio
selection QUBO with risk aversion q is:

    minimize    -mu^T x + q * x^T Sigma x   subject to x in {0,1}^n

The binary x_i selects whether asset i is included. After solving, weights
are equal-weighted across selected assets and normalized to sum to 1.
"""

from __future__ import annotations

import itertools

import numpy as np


def holdings_to_qubo(
    expected_returns: np.ndarray,
    covariance: np.ndarray,
    risk_aversion: float = 1.0,
    budget: int | None = None,
    budget_penalty: float = 5.0,
) -> np.ndarray:
    """Build a QUBO matrix Q such that minimizing x^T Q x solves the problem.

    Args:
        expected_returns: shape (n,)
        covariance: shape (n, n)
        risk_aversion: q ≥ 0 — higher means more risk-averse
        budget: optional integer count of assets to select
        budget_penalty: Lagrangian penalty weight for budget constraint
    """
    n = len(expected_returns)
    Q = risk_aversion * covariance.copy()
    # Add -mu on the diagonal (linear term)
    Q[np.diag_indices(n)] -= expected_returns

    # Budget constraint: penalty * (sum_i x_i - budget)^2
    if budget is not None:
        # Expanded: penalty * (sum x_i^2 + 2 sum_{i<j} x_i x_j - 2 budget sum x_i + budget^2)
        # x_i^2 = x_i for binary → goes on diagonal as penalty * (1 - 2*budget)
        Q[np.diag_indices(n)] += budget_penalty * (1.0 - 2.0 * budget)
        # Off-diagonal: 2 * penalty per pair
        for i in range(n):
            for j in range(i + 1, n):
                Q[i, j] += 2.0 * budget_penalty
                Q[j, i] += 2.0 * budget_penalty

    return Q


def qubo_energy(Q: np.ndarray, x: np.ndarray) -> float:
    """Evaluate x^T Q x for a binary vector x."""
    return float(x @ Q @ x)


def solve_qubo_classical(Q: np.ndarray) -> np.ndarray:
    """Brute-force QUBO solver — only viable for small n (≤ 16).

    Returns the binary vector that minimizes x^T Q x.
    """
    n = Q.shape[0]
    if n > 18:
        raise ValueError(f"Brute-force QUBO solver not viable for n={n} (max 18)")
    best_x = np.zeros(n, dtype=int)
    best_energy = float("inf")
    for bits in itertools.product([0, 1], repeat=n):
        x = np.array(bits, dtype=int)
        e = qubo_energy(Q, x)
        if e < best_energy:
            best_energy = e
            best_x = x
    return best_x


def solve_qubo_qaoa(
    Q: np.ndarray,
    depth: int = 2,
    steps: int = 100,
    learning_rate: float = 0.05,
) -> np.ndarray:
    """Solve QUBO via QAOA — returns the most-probable bitstring after optimization.

    Raises ImportError if PennyLane is not installed (caller should fall back).
    """
    from quantum.circuits import build_qaoa_circuit, sample_qaoa_solution

    try:
        import pennylane as qml  # type: ignore
        from pennylane import numpy as pnp  # type: ignore
    except ImportError as exc:
        raise ImportError("PennyLane is not installed") from exc

    circuit, n_assets = build_qaoa_circuit(Q, depth=depth)

    # Initialize parameters: gammas + betas, both shape (depth,)
    params = pnp.array([[0.5] * depth, [0.3] * depth], requires_grad=True)
    optimizer = qml.AdamOptimizer(stepsize=learning_rate)

    for _ in range(steps):
        params = optimizer.step(circuit, params)

    return sample_qaoa_solution(Q, np.array(params), depth=depth)


def bitstring_to_weights(x: np.ndarray) -> np.ndarray:
    """Convert binary selection to equal-weight allocation that sums to 1."""
    selected = x.sum()
    if selected == 0:
        # No assets selected — fall back to uniform allocation
        return np.ones(len(x)) / len(x)
    return x.astype(float) / selected
