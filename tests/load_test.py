"""Locust load test for the SIGMA API.

Run:

    pip install locust
    SIGMA_LOADTEST_BASE_URL=https://staging-api.sigma.dev \
    SIGMA_LOADTEST_API_KEY=sk_test_... \
    locust -f tests/load_test.py --host "$SIGMA_LOADTEST_BASE_URL"

Open http://localhost:8089 to drive load. Target: sustain ~100 RPS with p95 latency
under 500ms (cached) / 3s (fresh) per the launch acceptance criteria in
06_ROADMAP.md.

WARNING: only point this at staging or a dedicated load-test environment. Running
against production will burn through your rate limits and may violate hosted-service
terms.
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "SPY", "QQQ"]
TIMEFRAMES = ["daily", "4h", "hourly"]


class SignalsUser(HttpUser):
    """Simulates a typical API consumer mixing health checks and signal calls."""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.api_key = os.getenv("SIGMA_LOADTEST_API_KEY", "")
        if not self.api_key:
            print(
                "[warn] SIGMA_LOADTEST_API_KEY not set — only /health will be exercised. "
                "Authenticated endpoints will be skipped."
            )

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="GET /health")

    @task(8)
    def signal(self) -> None:
        if not self.api_key:
            return
        ticker = random.choice(TICKERS)
        timeframe = random.choice(TIMEFRAMES)
        self.client.post(
            "/signals",
            json={"ticker": ticker, "timeframe": timeframe},
            headers={"Authorization": f"Bearer {self.api_key}"},
            name="POST /signals",
        )

    @task(1)
    def usage(self) -> None:
        if not self.api_key:
            return
        self.client.get(
            "/usage",
            headers={"Authorization": f"Bearer {self.api_key}"},
            name="GET /usage",
        )
