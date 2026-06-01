"""Real-database end-to-end integration test (PR-O).

Skipped unless E2E_DATABASE_URL points at a real Postgres (so the normal mocked
suite + credential-free CI stay green). When set, it runs the proven offline
smoke (scripts/e2e_smoke.py) against that DB and asserts every link is green —
the durable version of the manual `make e2e` proof.

Enable locally:
    docker compose up -d postgres redis && make migrate && make seed
    E2E_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sigma \
      pytest tests/test_e2e_integration.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_E2E_DB = os.getenv("E2E_DATABASE_URL")
_API_DIR = Path(__file__).parents[1]


@pytest.mark.skipif(not _E2E_DB, reason="set E2E_DATABASE_URL to run the real-DB e2e test")
def test_e2e_smoke_runs_green():
    """The full loop persists real rows to a real Postgres (signal → order →
    position → label → evaluate → equity snapshot)."""
    env = {**os.environ, "DATABASE_URL": _E2E_DB}
    proc = subprocess.run(
        [sys.executable, "scripts/e2e_smoke.py", "--clean"],
        cwd=str(_API_DIR), env=env, capture_output=True, text=True, timeout=600,
    )
    # Surface the smoke's PASS/FAIL table on failure for easy diagnosis.
    tail = "\n".join(l for l in proc.stdout.splitlines() if "[PASS]" in l or "[FAIL]" in l or "checks passed" in l)
    assert proc.returncode == 0, f"e2e smoke failed:\n{tail}\n{proc.stderr[-2000:]}"
    assert "checks passed" in proc.stdout
