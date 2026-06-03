# SIGMA — API reference (trading & operations)

The **canonical** full API reference (signals, portfolio, backtest, keys, usage, **and** trading/ops) lives at the repo root:

**[`05_API_REFERENCE.md`](../05_API_REFERENCE.md)**

This path exists so [`docs/ROADMAP.md`](./ROADMAP.md) and M2 links resolve under `docs/`. Edit the root file only — do not fork endpoint shapes here.

---

## Sections added 2026-06 (audit & reporting slice)

| Section | Endpoints |
|---------|-----------|
| Trading & operations | Overview + internal auth headers |
| Positions | `GET /positions` |
| Orders | `GET /orders` |
| Execution | `GET /execution/status`, `POST /execution/pause\|resume\|run_cycle`, live guardrails |
| Strategies | `GET /strategies/performance`, `GET /strategies/performance/report` |
| Models | `GET /models/champions\|promotions\|evaluations`, promotion report + approve/reject |
| Worker health | `GET /health/worker` |

Operational procedures (pause, scale-down, restart): [`RUNBOOK_WORKER.md`](./RUNBOOK_WORKER.md).
