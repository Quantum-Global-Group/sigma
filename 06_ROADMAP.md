# SIGMA — Development Roadmap

> Concrete daily tasks. Each item has a clear done condition.
> No task ships without its test passing.

---

## Week 1 — Foundation (Ship one working endpoint)

**Goal:** `POST /signals` returns a real ML signal. Someone can call it with an API key and get billed.

### Day 1 — Repo + Local Environment

- [x] Create GitHub repo `sigma` (monorepo)
- [x] Add `docker-compose.yml` (Postgres 15 + TimescaleDB + Redis 7)
- [x] Add `Makefile` with `make dev`, `make test`, `make migrate`
- [x] Run `docker compose up -d` — all services healthy
- [x] Add `.env.example` with all required vars documented
- [x] Add `.gitignore` — excludes `.env*`, `__pycache__`, `.next`, `node_modules`

**Done when:** `docker compose ps` shows all services running.

---

### Day 2 — FastAPI Skeleton

- [x] `cd apps/api && pip install -r requirements.txt`
- [x] `main.py` — FastAPI app factory, CORS, lifespan hooks
- [x] `config.py` — Pydantic BaseSettings reading from `.env`
- [x] `routers/health.py` — `GET /health` returns `{"status": "ok"}`
- [x] `db/connection.py` — async SQLAlchemy engine + session
- [x] `db/models.py` — User, APIKey, UsageLog ORM models
- [x] `cache/redis.py` — Redis client with typed helpers
- [x] `middleware/auth.py` — extract + validate API key from header
- [x] `middleware/rate_limit.py` — sliding window counter in Redis
- [x] Run `001_initial_schema.sql` + `002_timescaledb.sql`
- [x] `scripts/seed_db.py` — insert test user + test API key

**Done when:** `curl http://localhost:8000/health` returns 200.

---

### Day 3 — Signal Pipeline MVP

- [x] `ml/data.py` — `fetch_ohlcv(ticker, days=60)` using yfinance
- [x] `ml/data.py` — `add_indicators(df)` adds RSI, MACD, BB via pandas-ta
- [x] `ml/inference.py` — `load_model(version)` loads `.pkl` from `MODEL_DIR`
- [x] `ml/inference.py` — `predict(features)` returns signal + confidence
- [x] `ml/pipeline.py` — `run_pipeline(ticker, timeframe)` orchestrates fetch → features → predict
- [ ] Train baseline ensemble model offline (`scripts/train_models.py`)
- [ ] Save model to `ml/saved_models/ensemble_v1.0.pkl`

**Done when:** `python -c "from ml.pipeline import run_pipeline; print(run_pipeline('AAPL'))"` prints a signal.

---

### Day 4 — Signal Endpoint + Auth

- [x] `models/signal.py` — `SignalRequest`, `SignalResponse` Pydantic models
- [x] `routers/signals.py` — `POST /signals` wired to pipeline
- [x] Check signal cache before running pipeline
- [x] Write result to `signal_history` + `signal_cache`
- [x] Log request to `usage_logs`
- [x] `tests/conftest.py` — test DB, mock Redis, test API client fixtures
- [x] `tests/test_signals.py` — happy path, invalid ticker, missing auth, rate limit

**Done when:** All tests pass. `curl -X POST localhost:8000/signals -H "Authorization: Bearer sk_test_xxx" -d '{"ticker":"AAPL"}'` returns a signal.

---

### Day 5 — Next.js Skeleton + Clerk

- [x] `npx create-next-app@latest apps/web --typescript --tailwind --app`
- [x] Install Clerk: `npm install @clerk/nextjs`
- [x] `app/layout.tsx` — wrap in `<ClerkProvider>`
- [x] `middleware.ts` — protect `/dashboard/*` routes
- [x] `app/(auth)/sign-in/.../page.tsx` — Clerk sign-in page
- [x] `app/(auth)/sign-up/.../page.tsx` — Clerk sign-up page
- [x] `app/page.tsx` — minimal landing page (hero + CTA)
- [x] `app/(marketing)/pricing/page.tsx` — 3-tier pricing cards
- [ ] Deploy to Vercel: `vercel --prod`

**Done when:** Landing page live at Vercel URL. Sign-up flow works. Dashboard redirects unauthenticated users.

---

## Week 2 — Billing, Dashboard, API Keys

**Goal:** User can sign up, create an API key, call the signal endpoint, and see usage tracked in a dashboard. Stripe billing is wired.

### Day 6 — Stripe Integration

- [x] Create Stripe account + test mode products
- [x] Create billing meter: `api_calls` (event-based)
- [x] Create prices: Free ($0), Pro ($99/mo), Enterprise ($499/mo)
- [x] `apps/api/billing/stripe.py` — `create_customer()`, `record_usage()`, `create_subscription()`
- [x] `apps/api/billing/limits.py` — `get_plan_limit(plan)`, `check_limit(user_id)`
- [x] Wire `record_usage()` call into `POST /signals` after successful response
- [x] `apps/web/app/api/webhooks/stripe/route.ts` — handle `invoice.paid`, `customer.subscription.deleted`
- [x] `apps/web/app/api/webhooks/clerk/route.ts` — upsert user on `user.created` / `user.updated`
- [x] `apps/api/routers/internal.py` — `POST /internal/users/upsert` + `POST /internal/users/sync-plan`
- [x] `packages/db/migrations/003_billing_events.sql` — run it

**Done when:** Calling the signal endpoint increments usage in Stripe dashboard.

---

### Day 7 — API Key Management

- [x] `routers/keys.py` — `GET /keys`, `POST /keys`, `DELETE /keys/{id}`
- [x] Key generation: `secrets.token_urlsafe(32)` → store SHA-256 hash, show raw once
- [x] `tests/test_auth.py` — valid key, revoked key, expired key, wrong format
- [x] `apps/web/app/(dashboard)/api-keys/page.tsx` — create/revoke keys UI
- [x] `apps/web/components/billing/UsageMeter.tsx` — progress bar

**Done when:** User can create a key in dashboard, use it to call the API, and see it listed.

---

### Day 8 — Usage + Billing Dashboard

- [x] `routers/usage.py` — `GET /usage` returns period summary
- [x] `apps/web/app/(dashboard)/dashboard/page.tsx` — metrics overview
- [x] `apps/web/app/(dashboard)/billing/page.tsx` — Stripe billing portal embed
- [x] `apps/web/lib/api.ts` — typed fetch wrappers for all backend endpoints
- [x] `apps/web/hooks/useUsage.ts` — SWR hook
- [x] `apps/web/app/(dashboard)/layout.tsx` — Sidebar + Header shell

**Done when:** Dashboard shows real API call count for current billing period.

---

### Day 9 — Signal Dashboard

- [x] `apps/web/app/(dashboard)/signals/page.tsx` — run signal from UI
- [x] `apps/web/components/signals/SignalForm.tsx` — ticker input + timeframe selector
- [x] `apps/web/components/signals/SignalCard.tsx` — BUY/SELL/HOLD result card
- [x] `apps/web/components/signals/SignalChart.tsx` — Recharts time-series of signal history
- [x] `apps/web/hooks/useSignal.ts` — SWR hook with optimistic UI

**Done when:** Can type AAPL in dashboard, click "Get Signal", see BUY/SELL/HOLD.

---

### Day 10 — Observability + Middleware Logging

- [x] Add Sentry to FastAPI (`sentry_sdk.init(dsn=...)`)
- [x] Add Sentry to Next.js (`@sentry/nextjs`)
- [x] `middleware/logging.py` — structured JSON logs per request
- [ ] Add Langfuse tracing to `ml/pipeline.py`
- [x] `tests/test_rate_limit.py` — verify rate limiting works correctly
- [x] `tests/test_ml/test_pipeline.py` — unit test each pipeline step

**Done when:** An intentional 500 error in FastAPI shows up in Sentry within 30 seconds.

---

## Week 3 — Portfolio Optimizer + Quantum Layer

**Goal:** Portfolio rebalancing endpoint live. Quantum QAOA option available. Backtest endpoint working.

### Day 11-12 — Portfolio Optimizer

- [ ] `models/portfolio.py` — `PortfolioRequest`, `RebalanceResponse`
- [ ] `quantum/portfolio_optimizer.py` — CVXPY MVO + QAOA (PennyLane)
- [ ] `quantum/qubo_solver.py` — QUBO formulation for portfolio selection
- [ ] `quantum/circuits.py` — PennyLane circuit definitions
- [ ] `routers/portfolio.py` — `POST /portfolio/rebalance`
- [ ] `packages/db/migrations/004_portfolio_snapshots.sql`
- [ ] `tests/test_portfolio.py` — valid holdings, invalid method, quantum timeout fallback

---

### Day 13-14 — Backtest Engine

- [ ] `models/backtest.py` — `BacktestRequest`, `BacktestResult`
- [ ] Core backtest logic — vectorized returns calculation
- [ ] `routers/backtest.py` — `POST /backtest/run`
- [ ] Portfolio dashboard UI — `HoldingsInput`, `AllocationChart`, `RebalanceOutput`
- [ ] Signal history page — `app/(dashboard)/signals/[ticker]/page.tsx`

---

### Day 15 — ML Models + Sentiment

- [ ] `ml/models/lstm.py` — LSTM price predictor (PyTorch)
- [ ] `ml/models/ensemble.py` — Random Forest + XGBoost ensemble
- [ ] `ml/models/quantum_hybrid.py` — QSVC wrapped with classical fallback
- [ ] `ml/sentiment.py` — FinBERT via HuggingFace Transformers → feature
- [ ] Retrain pipeline with new features
- [ ] `scripts/backfill_signals.py` — populate 90 days of historical signals

---

## Week 4 — Docs, Polish, Launch

**Goal:** Docs live, ProductHunt launch ready, first paying users.

### Day 16-17 — Docs + Marketing Site

- [ ] `app/(marketing)/docs/page.tsx` — docs landing
- [ ] `app/(marketing)/docs/[slug]/page.tsx` — MDX-rendered doc pages
- [ ] Write docs: Quick Start, Authentication, Endpoints, Rate Limits, Examples
- [ ] `components/marketing/FeatureGrid.tsx` — feature highlights section
- [ ] `components/layout/Footer.tsx` — links, legal

### Day 18 — Gumroad Digital Products

- [ ] Package React dashboard template → `.zip`
- [ ] Package ML boilerplate → `.zip`
- [ ] Upload 2-3 products to Gumroad
- [ ] Set pricing ($49–$99)
- [ ] Link from SIGMA landing page

### Day 19-20 — Launch Prep

- [ ] Set up custom domain (sigma.dev or similar)
- [ ] SSL cert auto-provisioned by Vercel
- [ ] Railway: set all prod env vars
- [ ] Load test: `locust -f tests/load_test.py` — verify 100 req/s holds
- [ ] Deploy to prod: `git push main` → Vercel auto-deploys
- [ ] Write ProductHunt launch copy
- [ ] Schedule ProductHunt launch (Wednesday 12:01 AM PST)
- [ ] Write Twitter launch thread (show backtest results, signal example)

---

## Ongoing (Month 2+)

- [ ] Weekly model retraining via cron (`scripts/train_models.py`)
- [ ] Monthly: review signal accuracy against actual market moves
- [ ] Add new endpoints based on user requests
- [ ] PostHog analytics — track conversion funnel
- [ ] Enterprise outreach — target quant teams via LinkedIn

---

## Acceptance Criteria (Launch-Ready Checklist)

- [x] `GET /health` returns 200
- [x] `POST /signals` returns a signal in < 500ms (cached) / < 3s (fresh)
- [ ] `POST /portfolio/rebalance` returns in < 5s
- [x] API key auth rejects invalid keys with 401
- [x] Rate limits enforce correctly across plans
- [ ] Stripe usage meter increments on each API call
- [x] User can sign up, create key, call API, see usage — in under 5 minutes
- [x] All unit tests pass (`pytest`)
- [ ] Zero Sentry errors in prod for 24 hours
- [ ] Landing page loads in < 2s (Vercel edge)
- [ ] Gumroad product page live with at least one product
