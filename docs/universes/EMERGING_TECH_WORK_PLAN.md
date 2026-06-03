# Emerging Tech 16 — work plan

Tracks **gaps between the PDF universe spec** and Sigma implementation. **Parallel research track** to M1 mega-cap paper — does not replace live `EQUITY_UNIVERSE` until live-trading items are explicitly done.

Canonical ticker list: [EMERGING_TECH_16.md](./EMERGING_TECH_16.md).

---

## Done (exists for any universe)

| Item | Description | Owner | Priority | Links |
|------|-------------|-------|----------|-------|
| Equity universe selector | `EQUITY_UNIVERSE` comma-list drives worker symbol set | Code | — | `apps/api/universe/equity_static.py` |
| OHLCV path | Alpaca → Tiingo for equity bars (training + worker) | Code | — | `apps/api/markets/equity_data.py`, `docs/MODELS.md` |
| Worker tick + audit | Per-tick `audit_records` + combiner/ensemble signals | Code | — | `apps/worker/tick.py` |
| Strategy performance API | Aggregates `signal_history` by strategy (no per-ticker filter) | Code | — | `apps/api/routers/strategy_reports.py`, `apps/api/ml/strategy_performance.py` |
| Weekly report endpoint | Markdown summary `GET /strategies/performance/report?period=7d` | Code | — | `05_API_REFERENCE.md`, `apps/web/app/(dashboard)/strategies/page.tsx` |
| Promotion report | Candidate vs incumbent `GET /models/promotions/{id}/report` | Code | — | `apps/api/ml/promotion_report.py` |
| Compare-universe CLI | Report-only multi-symbol strategy table; **ML preds empty** | Code | — | `apps/api/scripts/compare_universe_strategies.py` |
| pgvector MVP | Migration `012`, embed script, scheduler flag | Code | — | `packages/db/migrations/012_pgvector_embeddings.sql`, `apps/api/scripts/embed_signals.py` |
| Ensemble artifact path | `ensemble_v1.0.pkl` load + MLflow experiment naming | Code | — | `docs/MODELS.md`, `apps/api/ml/experiment.py` |

---

## In progress (M1 — mega-cap live path)

| Item | Description | Owner | Priority | Links |
|------|-------------|-------|----------|-------|
| DGX 24/7 paper worker | `EQUITY_UNIVERSE=AAPL,MSFT,NVDA,GOOG,AMZN` in `apps/api/.env`; observation, not emerging-tech | Operator | P0 | `docs/RUNBOOK_WORKER.md`, `make worker-local` |
| M1 observation window | 2+ weeks paper without manual intervention; weekly `/strategies` review | Operator | P0 | `docs/ROADMAP.md`, `docs/SPRINT1_DEPLOY_CHECKLIST.md` |
| Fly deploy (deferred) | Time-box when ready; fix `.dockerignore` before build | Operator | P1 | `docs/DEPLOY_EQUITY.md`, §Blockers in checklist |
| Prod migrations 001–012 | Applied on Tiger (2026-06-02) | Operator | — | `docs/SPRINT1_DEPLOY_CHECKLIST.md` |

---

## To do — report-only (no live switch)

Safe to execute **without** changing `EQUITY_UNIVERSE` or worker config.

| Item | Description | Owner | Priority | Links |
|------|-------------|-------|----------|-------|
| Run compare CLI on 16 tickers | One-off signal table vs PDF themes; verify Alpaca/Tiingo coverage per symbol | Operator | P0 | `apps/api/scripts/compare_universe_strategies.py` |
| Document CLI one-liner | Paste-ready `--symbols` for Emerging Tech 16 in MODELS + this doc | Operator | P1 | [EMERGING_TECH_16.md](./EMERGING_TECH_16.md), `docs/MODELS.md` |
| CLI preset flag | e.g. `--universe emerging-tech-16` reading canonical list (avoid typos) | Code | P1 | `compare_universe_strategies.py` |
| Load ML in compare script | Pass `model_predictions` from registry/ensemble for `ml` strategy row | Code | P1 | `compare_universe_strategies.py` (`model_predictions={}` today) |
| Per-ticker performance report | Extend API or script: filter `signal_history` / audit by `symbol` | Code | P2 | `strategy_performance.py`, new query params or script |
| Backfill / shadow signals | Optional: run compare or offline backtest to populate research tables (no orders) | Operator | P2 | — |

**Example (today — manual symbols):**

```bash
cd apps/api
PYTHONPATH=. python scripts/compare_universe_strategies.py --asset-class equity \
  --symbols IONQ RGTI QBTS QUBT RKLB JOBY ACHR QS SLDP SMR CRSP NTLA BEAM BE PLUG SPCE \
  --strategies momentum,ict,ml
```

---

## To do — live trading (when ready)

**Gate:** M1 mega-cap observation stable + explicit go/no-go. Changing `EQUITY_UNIVERSE` affects worker, rate limits, and model validity.

| Item | Description | Owner | Priority | Links |
|------|-------------|-------|----------|-------|
| Alpaca tradability preflight | Per-symbol: active, shortable if needed, min liquidity; block removed PDF names | Operator + Code | P0 | Alpaca assets API; new hygiene script (TBD) |
| Ticker hygiene preflight | Reject LILM/ASTR/MMAT/BLUE/IRBT; map RWLK→LFWD, EKSO→CHRN | Code | P0 | Future registry; `EMERGING_TECH_16.md` blocklist |
| `EQUITY_UNIVERSE` switch | Set 16 (or phased subset) on worker + Fly `[env]` | Operator | P0 | `.env.example`, `apps/worker/fly.toml`, **do not edit prod without checklist** |
| Rate limits / tick budget | 16 high-beta names vs 5 mega-caps: Alpaca/Tiingo quotas, worker cycle time | Operator | P1 | `apps/worker/tick.py`, provider configs |
| Retrain equity ensemble | Features/labels on new universe; promote via MLflow + promotion report | Operator + Code | P0 | `scripts/train_ranking.py`, `docs/MODELS.md` |
| Paper soak on 16 | 2+ weeks after switch, same M1 criteria | Operator | P0 | `docs/ROADMAP.md` M1 |

---

## To do — PDF alignment (product / risk)

Implements PDF **Recommended Strategy Framework** and implementation guidance — not required for first compare CLI run.

| Item | Description | Owner | Priority | Links |
|------|-------------|-------|----------|-------|
| Universe YAML/JSON registry | `ticker`, `canonical_symbol`, `sector`, `action`, `risk_tier`, `theme_cap`, `notes`; block stale symbols | Code | P1 | New `packages/` or `apps/api/universe/` file (TBD) |
| Theme exposure caps | Max weight per theme (quantum, space, …); PDF portfolio layer | Code | P1 | Combiner / portfolio optimizer (TBD) |
| Speculative sleeve sizing | Lower max notional for QUBT, SPCE vs primaries | Code | P1 | Risk module / sizing in worker (TBD) |
| Two-confirmation signal gating | Entry requires 2 of: trend+momentum, trend+volume, catalyst+breakout | Code | P2 | Strategy combiner or new gate (TBD) |
| ATR / vol targeting stops | PDF risk layer; partial overlap with existing sizing | Code | P2 | Execution / risk code paths |
| Deterministic baseline first | PDF: stable rules before ML; document current vs target | Operator | P1 | `docs/MODELS.md`, ROADMAP backlog |

---

## Parking lot

Explicitly **out of active to-do** until report-only + M1 paths are stable. Do not schedule alongside P0 report-only work.

| Item | Description | Owner | Priority | Links |
|------|-------------|-------|----------|-------|
| Public-sector validation layer | Confirm pure-play moves when IBM, NVDA, LMT, PLTR, … strengthen (PDF macro feature) | Code / Research | P2 | PDF §public-sector; no Sigma module yet |
| Moomoo / options expansion | Separate asset class; not Emerging Tech 16 equity scope | Operator | P2 | `docs/DEPLOY_OPTIONS.md` |
| Fly production deploy | M1 Fly soak when DGX observation sufficient | Operator | P2 | `docs/SPRINT1_DEPLOY_CHECKLIST.md` |
| pgvector embed at scale | `EMBED_SIGNALS_ENABLED=true` on DGX/Timescale for traded + research symbols | Operator | P2 | `scripts/embed_signals.py`, migration `012` |
| Full 31-stock table automation | Import PDF quarantine/watchlist rows into registry | Code | P3 | PDF appendix table |
| TradeFluxSimulator parity | Shared universe registry across repos | Operator | P3 | External repo |

---

## Suggested order (operator)

1. **P0 report-only:** Run compare CLI on 16 tickers; note fetch failures / thin history.
2. **P1 code:** CLI preset + ML predictions in compare script.
3. **Continue M1:** Mega-cap worker observation (unchanged universe).
4. **Before live 16:** Tradability + hygiene + ensemble retrain + paper soak.
5. **PDF alignment:** Registry → theme caps → speculative sleeve → signal gating.

---

## Cross-links

- [EMERGING_TECH_16.md](./EMERGING_TECH_16.md) — ticker table, blocklist, watchlist
- [README.md](./README.md) — doc index
- [ROADMAP.md](../ROADMAP.md) — M1 milestone (mega-cap operational)
- [MODELS.md](../MODELS.md) — ensemble, promotion reports, compare CLI
- [SPRINT1_DEPLOY_CHECKLIST.md](../SPRINT1_DEPLOY_CHECKLIST.md) — deploy blockers + parallel tracks
