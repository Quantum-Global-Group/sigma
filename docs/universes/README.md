# Universe documentation

Sigma supports multiple **asset-class universes** (equity, crypto, forex, options). This folder documents **named equity research universes** that may differ from the **live worker** symbol list.

---

## Emerging Tech 16 (parallel research track)

| Doc | Purpose |
|-----|---------|
| [EMERGING_TECH_16.md](./EMERGING_TECH_16.md) | Canonical 16 tickers, themes, roles, risk tiers, blocklist, watchlist, vs `EQUITY_UNIVERSE` |
| [EMERGING_TECH_WORK_PLAN.md](./EMERGING_TECH_WORK_PLAN.md) | Done / in-progress / to-do / parking lot with priorities and file links |

**Source spec (local, do not commit):** `~/emerging_tech_trading_universe_report.pdf` (June 2, 2026).

**Live worker today:** mega-cap `EQUITY_UNIVERSE` (e.g. `AAPL,MSFT,NVDA,GOOG,AMZN`) — see `apps/api/universe/equity_static.py` and operator `.env`. Emerging Tech 16 is **report-first** until the work plan’s live-trading section is complete.

---

## Related Sigma docs

| Doc | Relevant sections |
|-----|-------------------|
| [MODELS.md](../MODELS.md) | Equity ensemble, promotion reports, **Strategy comparison CLI** |
| [ROADMAP.md](../ROADMAP.md) | M1 internal alpha, audit & reporting slice, Sprint 1 deploy |
| [SPRINT1_DEPLOY_CHECKLIST.md](../SPRINT1_DEPLOY_CHECKLIST.md) | Fly/DGX deploy steps, blockers, parallel tracks |
| [05_API_REFERENCE.md](../05_API_REFERENCE.md) | `GET /strategies/performance`, `/report` |
| [RUNBOOK_WORKER.md](../RUNBOOK_WORKER.md) | Local/Fly worker operation |
| [DEPLOY_EQUITY.md](../DEPLOY_EQUITY.md) | Equity production runbook |

---

## Other universes (code, not yet doc’d here)

| Mechanism | Location |
|-----------|----------|
| Equity (env) | `EQUITY_UNIVERSE` → `apps/api/universe/equity_static.py` |
| Crypto | `apps/api/universe/crypto_dynamic.py` |
| Forex | `apps/api/universe/forex_static.py` |
| Options | `apps/api/universe/option_universe.py` |

Future: YAML/JSON registry for named universes (Emerging Tech 16 first consumer) — see work plan **PDF alignment** section.
