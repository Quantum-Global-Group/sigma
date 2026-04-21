"""
Portfolio rebalance endpoint tests.
All external calls (yfinance, CVXPY, QAOA) are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


MOCK_OPTIMIZE_RESULT = {
    "method": "mvo",
    "fallback": False,
    "target_allocation": {"AAPL": 0.4, "MSFT": 0.6},
    "recommended_trades": [
        {"ticker": "AAPL", "action": "SELL", "amount": 200.0},
        {"ticker": "MSFT", "action": "BUY", "amount": 200.0},
    ],
    "sharpe_ratio": 1.42,
}


@pytest.fixture
def mock_optimize():
    async def _async_optimize(*args, **kwargs):
        return MOCK_OPTIMIZE_RESULT

    with patch("routers.portfolio.optimize", side_effect=_async_optimize):
        yield


@pytest.fixture
def mock_persist():
    with patch("routers.portfolio._persist_snapshot", new_callable=AsyncMock):
        yield


class TestRebalanceEndpoint:
    def test_valid_holdings_returns_200(self, client, mock_optimize, mock_persist):
        resp = client.post(
            "/portfolio/rebalance",
            json={"holdings": {"AAPL": 1000.0, "MSFT": 1500.0}, "method": "mvo"},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "mvo"
        assert body["fallback"] is False
        assert body["target_allocation"] == {"AAPL": 0.4, "MSFT": 0.6}
        assert len(body["recommended_trades"]) == 2
        assert body["sharpe_ratio"] == 1.42

    def test_empty_holdings_returns_422(self, client):
        resp = client.post(
            "/portfolio/rebalance",
            json={"holdings": {}, "method": "mvo"},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 422

    def test_negative_amount_returns_422(self, client):
        resp = client.post(
            "/portfolio/rebalance",
            json={"holdings": {"AAPL": -100.0}, "method": "mvo"},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 422

    def test_invalid_method_returns_422(self, client):
        resp = client.post(
            "/portfolio/rebalance",
            json={"holdings": {"AAPL": 1000.0}, "method": "magic_method"},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 422

    def test_fetch_data_value_error_returns_422(self, client, mock_persist):
        async def _raise(*args, **kwargs):
            raise ValueError("No data for ticker XXXX")

        with patch("routers.portfolio.optimize", side_effect=_raise):
            resp = client.post(
                "/portfolio/rebalance",
                json={"holdings": {"XXXX": 1000.0}, "method": "mvo"},
                headers={"Authorization": "Bearer test"},
            )
        assert resp.status_code == 422

    def test_quantum_falls_back_to_mvo(self, client, mock_persist):
        fallback_result = {**MOCK_OPTIMIZE_RESULT, "fallback": True}

        async def _async_optimize(*args, **kwargs):
            return fallback_result

        with patch("routers.portfolio.optimize", side_effect=_async_optimize):
            resp = client.post(
                "/portfolio/rebalance",
                json={"holdings": {"AAPL": 1000.0, "MSFT": 1500.0}, "method": "quantum_qaoa"},
                headers={"Authorization": "Bearer test"},
            )
        assert resp.status_code == 200
        assert resp.json()["fallback"] is True


class TestQUBOSolver:
    def test_holdings_to_qubo_shape(self):
        from quantum.qubo_solver import holdings_to_qubo
        mu = np.array([0.05, 0.08, 0.10])
        Sigma = np.eye(3) * 0.04
        Q = holdings_to_qubo(mu, Sigma, risk_aversion=1.0)
        assert Q.shape == (3, 3)

    def test_classical_solver_finds_minimum(self):
        from quantum.qubo_solver import qubo_energy, solve_qubo_classical
        Q = np.array([[-1.0, 0.0], [0.0, -2.0]])
        x = solve_qubo_classical(Q)
        # Optimal is x = [1, 1] with energy -3
        assert qubo_energy(Q, x) == -3.0

    def test_bitstring_to_weights_normalises(self):
        from quantum.qubo_solver import bitstring_to_weights
        x = np.array([1, 1, 0, 1])
        w = bitstring_to_weights(x)
        assert abs(w.sum() - 1.0) < 1e-9
        assert w[2] == 0.0

    def test_bitstring_to_weights_empty_falls_back_to_uniform(self):
        from quantum.qubo_solver import bitstring_to_weights
        w = bitstring_to_weights(np.zeros(4, dtype=int))
        assert abs(w.sum() - 1.0) < 1e-9
        assert all(abs(wi - 0.25) < 1e-9 for wi in w)


class TestOptimizeMVO:
    def test_mvo_weights_sum_to_one(self):
        from quantum.portfolio_optimizer import optimize_mvo

        with patch("quantum.portfolio_optimizer._expected_returns_and_cov") as mock_data:
            mock_data.return_value = (
                np.array([0.10, 0.08, 0.12]),
                np.array([[0.04, 0.005, 0.01], [0.005, 0.03, 0.008], [0.01, 0.008, 0.05]]),
            )
            result = optimize_mvo({"AAPL": 1000.0, "MSFT": 1000.0, "GOOG": 1000.0})

        assert abs(sum(result["weights"]) - 1.0) < 1e-6
        assert all(w >= -1e-6 for w in result["weights"])
        assert "sharpe_ratio" in result
