# LIAISON PROJECT BRIEF — sigma

> Machine: DGX Spark | Org: quantumGlobalGroup | Phase: MVP
> Path: `~/quantumGlobalGroup/sigma`
> Last updated: 2026-05-30

---

## Problem statement

Sigma is an ML-powered trading signal API with quantum-hybrid portfolio optimization, multi-asset coverage (equities + crypto), and a live paper-trading worker — the active integration target for tradeFluxsimulator archive migration.

---

## Happy path

```bash
cd ~/quantumGlobalGroup/sigma
liaison doctor
liaison validate --profile sigma
# Expected: SIGMA CHECK PASS: 222 passing
```

---

## Non-goals

- Live production trading (paper-trading only on DGX Spark)
- Full tradeFluxsimulator merge in L2 scope (deferred to L4)

---

## Validation profile

| Field | Value |
|-------|-------|
| Profile | `sigma` |
| Script | `~/spark/agent-system/checks/sigma.sh` |
| Smoke command | `cd ~/quantumGlobalGroup/sigma && liaison validate --profile sigma` |

```bash
cd ~/quantumGlobalGroup/sigma
liaison validate --profile sigma
# 222/230 passing; 8 async failures tracked (pre-existing)
```

---

## Hub pattern and recommended agents

| Agent | Role |
|-------|------|
| hermes | Product engineering, git, tests, Kanban — default execution path |
| codex | Minimal patches for API and migration fixes |

Pattern: `sigma-integration` (see `~/spark/agent-system/workflows/sigma-integration.yaml`)

---

## Open risks

| Risk | Mitigation |
|------|------------|
| Financial risk — API keys | Keep all API keys in `.env` (gitignored); never commit |
| Async test failures (8) | Install `pytest-asyncio` in `apps/api/.venv`; tracked in improvements |
| tradeFluxsimulator merge scope | Archive is read-only; integration scoped per reporter slice; full merge in L4 |

---

## Related

- [project_profile.yaml](../.spark-flow/project_profile.yaml)
- [.spark-flow/README.md](../.spark-flow/README.md)
- [projects/sigma-integration.md](~/spark/docs/local-agents/projects/sigma-integration.md)
- Task: `sigma-tfs-001` (closed L1) — backup at `.spark-flow/tasks/sigma-tfs-001-legacy-executor/`

---

## L4 Domain Risk Review — Financial (2026-05-31)

**Review scope:** financial domain — paper trading gate, API key hygiene, backtest labeling

| Control | Status | Evidence |
|---------|--------|----------|
| No live API keys in `.spark-flow/` | PASS | No brokerage credentials found in git |
| Backtest outputs labeled as research | PASS | Signal outputs treated as research artifacts |
| risk_metric boundaries documented | INFO | Sigma ratio calculations bounded by input data range |

**Risk classification:** LOW-MEDIUM — statistical research tool; no live order routing.

**Decision:** Accept current risk posture. Follow-up: confirm no yfinance live calls wired to trading endpoints (L5).
