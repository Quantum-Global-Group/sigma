# SIGMA Roadmap

Working doc for what's coming next. Single-source-of-truth for milestones, sprints, and backlog. Updated as scope shifts — don't treat dates as commitments.

**Operating mode:** solo, side-project, ~20h per 2-week sprint. Scope is deliberately small per sprint so things actually finish.

**Next milestone:** Internal alpha — running the merged sigma+razorBill stack for myself in paper mode. No customer surface yet.

> **Companion doc:** [`/06_ROADMAP.md`](../06_ROADMAP.md) at the repo root holds the granular, day-by-day checklist with explicit done-when criteria. Use that for Sprint 1's detailed task list; use this doc for milestone strategy and the long backlog.

---

## Milestones

### M1 — Internal alpha (paper) · target: 8 weeks from PR #1 merge

Success criteria:
- Worker runs on Railway for 2+ consecutive weeks without manual intervention
- Trained `crypto_ranking_v1.0.pkl` artifact in production, not the heuristic fallback
- Daily signal log + weekly trade-review habit established
- Sentry shows ≤1 unique exception per week
- A go/no-go decision on M2 is informed by real observed behavior

### M2 — Beta (paper, multi-tenant) · target: after M1 + 4 weeks observation

Success criteria:
- `/signals?asset_class=crypto` exposed to Pro+ customers
- Stripe metering correct (no internal traffic billed; no crypto calls free)
- Public web pages for crypto signals (Clerk-authed, no plaintext key boxes)
- API reference docs for positions/orders/execution endpoints
- 1+ external user trying it without paid handholding

### M3 — Production (sandbox → live) · target: when M2 has 4+ weeks of clean traffic

Success criteria:
- `EXECUTOR_MODE=coinbase` with sandbox keys, full order roundtrip captured in `orders` table for 2 weeks
- Switch to live keys with a hard cap on per-day notional
- DR runbook (`DEPLOY.md` updated): how to stop the worker, reconcile open positions, restart
- Real-money trading on the house book, no customer-facing live execution

---

## Active sprint — Sprint 0 (PR #1 close-out)

**Goal:** get PR #1 reviewed and merged. No new feature scope.

Working items (each is a checkbox; closing all of them ends the sprint):

- [ ] **Decide WIP commit `81ee40b`** — squash into merge commit, split into a separate PR, or `git reset` and re-stage in pieces. (Reviewer-facing decision; affects history clarity.)
- [ ] **Self-review the diff** — skim 18 commits with fresh eyes against [PR #1](https://github.com/Quantum-Global-Group/sigma/pull/1).
- [ ] **Resolve `06_ROADMAP.md` conflict** — currently dirty on `feat/razorbill-merge`. Either fold into this `docs/ROADMAP.md` or rebase.
- [ ] **Add `gh pr edit 1 --add-reviewer @user`** if someone external is reviewing; otherwise self-merge.
- [ ] **CI green** — GitHub Actions doesn't exist yet on sigma. Decide: add minimal pytest workflow now, or merge without CI and add it M1 Sprint 1.
- [ ] **Merge to `main`** (squash or rebase — pick once, document choice).
- [ ] **Archive `iconbaypark2900/razorBill`** on GitHub (Settings → Archive). One click.
- [ ] **Delete `feat/razorbill-merge`** locally + remote after merge.

Cleanup that's already done:
- [x] razorBill local branch `claude/tender-curie-ebee21` deleted (worktree directory leftover; cleans up on session end)
- [x] Migrations 001–006 applied + schema verified locally (postgres + timescaledb)
- [x] pytest: 100/100 green (commit `33ee859`)
- [x] Dockerfile bumps to `python:3.12-slim` + `.dockerignore` committed (commit `f955541`)
- [x] `docker-compose.override.yml` added to `.gitignore` (local-only port-conflict workaround stays out of git)

---

## M1 — Internal alpha

### Sprint 1 — Deploy + first model train (2 weeks)

| # | Task | Notes | Est |
|---|---|---|---|
| 1 | Provision Fly.io apps (`sigma-api`, `sigma-worker`) | `fly launch --copy-config --no-deploy` for each. Region: `ord`. Single VM each. `fly.toml`s already live in `apps/{api,worker}/`. | 2h |
| 2 | Provision Postgres + Redis | Timescale Cloud (free 30 days) or Crunchy Bridge for Postgres-with-timescaledb; Upstash for Redis | 1h |
| 3 | Set production secrets on both Fly apps | `fly secrets set` — `INTERNAL_SECRET` (shared), `DATABASE_URL`, `REDIS_URL`, `EXECUTOR_MODE=paper`, `WORKER_ASSET_CLASSES=crypto`, `SENTRY_DSN`, `LANGFUSE_*`, `HUGGINGFACE_TOKEN` | 1h |
| 4 | Run migrations 001–006 against the prod Postgres | psql from your laptop using the Fly secret, document in `DEPLOY.md` | 1h |
| 5 | `make train-ranking` against Coinbase historical 5m candles | 30–60 days lookback, save `crypto_ranking_v1.0.pkl` | 3h |
| 6 | Bundle the trained artifact into worker image | Either `COPY ml/saved_models/` (need .dockerignore tweak) or runtime download from S3 | 2h |
| 7 | `fly deploy` both apps | `apps/api`: `fly deploy`; `apps/worker`: `fly deploy -a sigma-worker --config apps/worker/fly.toml --dockerfile apps/worker/Dockerfile .` | 1h |
| 8 | Worker tail green: one healthy tick every interval | `fly logs -a sigma-worker`; smoke check that orders + positions rows appear | 2h |
| 9 | Sentry capturing worker tick exceptions | Currently only initialized on api `lifespan`; add to `apps/worker/main.py` | 2h |
| 10 | Sprint 1 retro note in this file | Honest about what went over scope | 0.5h |

Sprint capacity: ~16h. Buffer: 4h.

> The CI workflow that was originally listed as Sprint 1 work (`.github/workflows/ci.yml`) shipped in Sprint 0 as part of PR #3. Pytest + npm type-check run on every push and PR against `main`.

### Sprint 2 — Observability + review cadence (2 weeks)

| # | Task | Notes | Est |
|---|---|---|---|
| 1 | Langfuse spans inside `worker.tick.tick_once` | Per-symbol child span; visibility into combiner score breakdown | 4h |
| 2 | `apps/api/routers/health.py::/health/worker` | Returns last_tick_at, last_signal_count, last_error | 2h |
| 3 | Daily digest cron — orders + signal_history summary | Email or Slack via a Railway scheduled job | 4h |
| 4 | Position reconciliation on worker startup | Sanity-check open positions vs broker (paper: just self-consistent) | 3h |
| 5 | `make train-ranking` rerun cadence | Decide: weekly retrain? on what dataset? Doc the answer in `docs/MODELS.md` (new) | 2h |
| 6 | Sprint 2 retro | | 0.5h |

### Sprint 3 — Stability + risk knobs (2 weeks)

Carries the still-open PR #1 risks plus alpha learnings.

| # | Task | Notes | Est |
|---|---|---|---|
| 1 | Plumb `use_atr_trailing` + `use_partial_profits` through config | Currently default-off via function defaults — make explicit `Settings` fields | 2h |
| 2 | Partial-fill broker-view reconciliation | Compare orders table to Coinbase fills (paper: still useful for testing the reconciler) | 4h |
| 3 | Retry + circuit-breaker on `executor.place()` failures | Today exceptions log + continue; add bounded retry with exponential backoff | 3h |
| 4 | Coinbase public-API rate limit handling | The current `time.sleep(0.1)` in `_fetch_paginated` is a courtesy, not a budget | 2h |
| 5 | Worker graceful shutdown test | SIGTERM mid-tick should complete current symbol then exit | 2h |
| 6 | Sprint 3 retro | | 0.5h |

### Sprint 4 — Alpha review + M1 → M2 decision (2 weeks)

| # | Task | Notes | Est |
|---|---|---|---|
| 1 | 2 weeks of observation, weekly retros | Trade log review, signal-quality sanity check | 4h |
| 2 | Decision doc: extend alpha, move to M2, or pivot | Written rationale committed to `docs/decisions/001-alpha-outcome.md` | 2h |
| 3 | Backfill any tech-debt items the alpha surfaced | Pull from backlog | 8h |
| 4 | Update M2 sprint plan based on what we learned | Edit this file | 1h |

---

## M2 — Beta (paper, multi-tenant)

High-level outline; sprints get planned after M1 closes.

- Stripe metering correctness audit — distinguish `asset_class=crypto` calls from equity in usage_logs
- Pricing decision — fold crypto signals into Pro, or new "Crypto" tier? Stripe price IDs, plan upgrade flow
- Web pages — remove plaintext API key input on positions/orders/execution; integrate Clerk session
- API reference docs for new endpoints (`docs/05_API_REFERENCE.md`)
- Rate-limit fairness across asset classes
- Customer-facing changelog
- Beta-user invite flow

---

## M3 — Production (sandbox → live)

Outline — needs M2 learnings to refine.

- Coinbase Advanced Trade sandbox keys provisioned + tested for 2 weeks
- Per-day notional cap enforcement (server-side, not just config)
- Risk circuit breaker — single switch to halt all worker buys
- `DEPLOY.md` updated with: rollback strategy, position reconcile under stress, on-call rotation
- Multi-region postgres consideration
- Disaster recovery dry-run

---

## Backlog

Unsorted, untimed. Items move into a sprint when they earn it. Tagged by area for grep.

### Trading core

- **Per-symbol RankingModel option** — registry tries `crypto_ranking_{symbol}_v.pkl` first, falls back to shared
- **Backtest endpoint extended for crypto** — `/backtest/run` currently equity-only via yfinance; needs crypto-aware data source
- **Multi-timeframe filter wired in** — `apps/api/ml/multi_timeframe.py` ported but unused by the combiner
- **`load_exit_state` / `save_exit_state` stub cleanup** — risk/exits.py still has the no-op stubs; remove once nothing imports them
- **Per-asset-class worker tick cadence override via DB, not env** — supports operator changing 5m → 1m without redeploy
- **Sentiment provider end-to-end test against real Ollama** — currently mock-only

### Operations

- **Railway → Fly.io evaluation** — if Railway pricing or quotas become a problem
- **Postgres backup automation** — pgbackrest or Railway's built-in
- **Worker single-instance guarantee** — Railway might spin two; need a Redis-backed lock or a single replica enforced
- **Migration rollback script** — currently forward-only; document the rollback path for 005/006
- **Secrets rotation drill** — `INTERNAL_SECRET`, Coinbase keys, Stripe webhook secret

### Frontend

- **Recharts: positions PnL over time** — currently only an aggregate row
- **WebSocket signal stream** — replace 15s/30s polling on orders/positions
- **shadcn/ui pass on the new pages** — match the rest of the dashboard's component library
- **Mobile responsiveness audit** on `/positions`, `/orders`, `/execution`
- **Sidebar: feature flag per asset class** — hide crypto nav for free-tier users

### ML / research

- **Hyperparameter tuning script** — Optuna on the RankingModel knobs (lgb_n_estimators, learning_rate, max_depth, etc.)
- **Rank IC reporting in CI** — fail PR if rank_ic drops > 20% on a held-out set
- **Sentiment-feature gating** — currently sentiment_score is added if headlines + token present; needs an explicit toggle so we can A/B sentiment-on vs sentiment-off
- **FinBERT vs LangExtract head-to-head** on real headline data
- **Online learning option** — SGDRegressor refit weekly on the latest window instead of full retrain

### Tech debt from the merge

- **`StripeEvents` table integration verification** — exists in schema, not sure every webhook handler writes to it
- **Naive partial-fill math in `_apply_fill_to_position`** — `_PR #1 risks` lists this; tighten when live trading nears
- **CRLF warnings on every git op** — set `core.autocrlf=false` repo-wide, or add `.gitattributes`
- **`test_rate_limit.py` AsyncMock warnings** — coroutine never awaited; cosmetic but noisy
- **Duplicate `06_ROADMAP.md`** — exists at repo root from the WIP commit; either fold into `docs/ROADMAP.md` (this file) or delete
- **Streamlit dashboards** in `_legacy_razorbill/` deleted; no Streamlit code remains, but `.env.example` no longer mentions any Streamlit env vars (verify)

### Documentation

- **`docs/MODELS.md`** — training, retraining, artifact naming, registry behavior
- **`docs/DEPLOY_RAZORBILL.md`** or fold into existing `DEPLOY.md` — new env vars, worker service setup
- **`docs/05_API_REFERENCE.md`** — positions / orders / execution endpoint shapes
- **`docs/decisions/`** ADR folder — start with the squash-vs-rebase decision from Sprint 0
- **Runbook: "worker started doing X, here's how to stop it safely"**

### Open product questions

- **Pricing tier for crypto** — same as equity Pro plan? New tier? Per-signal pricing?
- **Multi-tenant trading** vs house-book-only — huge scope difference; M3+ if ever
- **Free-tier behavior on `asset_class=crypto`** — allow N free crypto calls/day or hard block?
- **Custom universe per customer** — backlog item or never?

---

## Notes on cadence

Each sprint should end with a one-paragraph retro in this file under the sprint header — what shipped, what didn't, what surprised. The retro is the only required artifact; everything else is optional. The goal is honesty about velocity, not theater.

If a sprint goes over by >25%, the next sprint is smaller, not bigger. If it goes under, pull from backlog at the *start* of the next sprint, not mid-flight.
