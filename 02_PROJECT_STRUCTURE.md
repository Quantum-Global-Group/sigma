# SIGMA — Project Structure

> Every file and directory in the project. Build in the order shown.
> Numbers in parentheses = which week to create it.

---

## Repository Layout

```
sigma/
├── apps/
│   ├── web/                        # Next.js frontend + API gateway
│   └── api/                        # FastAPI backend (signals, ML, quantum)
├── packages/
│   ├── db/                         # Shared DB schema + migrations
│   └── types/                      # Shared TypeScript types
├── docker-compose.yml              # Local dev: Postgres + TimescaleDB + Redis
├── docker-compose.prod.yml         # Prod parity check
├── .env.example                    # All required env vars documented
├── .gitignore
├── README.md
└── Makefile                        # Dev shortcuts (make dev, make test, make migrate)
```

---

## `apps/web/` — Next.js Frontend + API Gateway

```
apps/web/
├── app/
│   ├── layout.tsx                  # Root layout — Clerk provider, Stripe, fonts (W1)
│   ├── page.tsx                    # Landing page (W1)
│   ├── globals.css                 # Tailwind base styles (W1)
│   │
│   ├── (auth)/
│   │   ├── sign-in/
│   │   │   └── [[...sign-in]]/
│   │   │       └── page.tsx        # Clerk sign-in page (W1)
│   │   └── sign-up/
│   │       └── [[...sign-up]]/
│   │           └── page.tsx        # Clerk sign-up page (W1)
│   │
│   ├── (marketing)/
│   │   ├── pricing/
│   │   │   └── page.tsx            # Pricing tiers — Free / Pro / Enterprise (W1)
│   │   └── docs/
│   │       ├── page.tsx            # Docs landing (W2)
│   │       └── [slug]/
│   │           └── page.tsx        # Individual doc page (W2)
│   │
│   └── (dashboard)/
│       ├── layout.tsx              # Dashboard shell — sidebar, header (W2)
│       ├── dashboard/
│       │   └── page.tsx            # Overview — MRR, API calls, signal summary (W2)
│       ├── signals/
│       │   ├── page.tsx            # Signal explorer — run signals, view history (W2)
│       │   └── [ticker]/
│       │       └── page.tsx        # Single ticker deep-dive (W3)
│       ├── portfolio/
│       │   └── page.tsx            # Portfolio optimizer UI (W3)
│       ├── api-keys/
│       │   └── page.tsx            # Create/revoke API keys, view usage (W2)
│       ├── strategies/
│       │   └── page.tsx            # Strategy performance dashboard (equity + 7d) (2026-06)
│       └── billing/
│           └── page.tsx            # Stripe billing portal embed (W2)
│
├── api/                            # Vercel serverless functions (API gateway)
│   ├── webhooks/
│   │   └── stripe.ts               # Stripe webhook handler (W2)
│   └── auth/
│       └── [...clerk].ts           # Clerk auth handler (W1)
│
├── components/
│   ├── ui/                         # shadcn/ui generated components (W1)
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── dialog.tsx
│   │   ├── input.tsx
│   │   ├── table.tsx
│   │   └── badge.tsx
│   │
│   ├── layout/
│   │   ├── Sidebar.tsx             # Dashboard sidebar nav (W2)
│   │   ├── Header.tsx              # Top bar — user menu, notifications (W2)
│   │   └── Footer.tsx              # Marketing footer (W1)
│   │
│   ├── marketing/
│   │   ├── Hero.tsx                # Landing hero — headline, CTA, demo (W1)
│   │   ├── PricingCard.tsx         # Individual pricing tier card (W1)
│   │   └── FeatureGrid.tsx         # Features section (W1)
│   │
│   ├── signals/
│   │   ├── SignalCard.tsx          # Single signal result card (W2)
│   │   ├── SignalChart.tsx         # Signal time-series chart (Recharts) (W2)
│   │   ├── SignalForm.tsx          # Ticker input + submit (W2)
│   │   └── SignalHistory.tsx       # Past signals table (W3)
│   │
│   ├── portfolio/
│   │   ├── HoldingsInput.tsx       # Upload/input current holdings (W3)
│   │   ├── AllocationChart.tsx     # Pie chart — current vs target (W3)
│   │   └── RebalanceOutput.tsx     # Recommended trades table (W3)
│   │
│   └── billing/
│       ├── UsageMeter.tsx          # API calls used / limit bar (W2)
│       └── PlanBadge.tsx           # Current plan indicator (W2)
│
├── lib/
│   ├── stripe.ts                   # Stripe client + helpers (W2)
│   ├── clerk.ts                    # Clerk server helpers (W1)
│   ├── api.ts                      # Typed fetch wrappers → FastAPI backend (W2)
│   └── utils.ts                    # cn(), formatCurrency(), formatDate() (W1)
│
├── hooks/
│   ├── useSignal.ts                # SWR hook — fetch + cache signal (W2)
│   ├── useUsage.ts                 # SWR hook — API usage this billing period (W2)
│   └── usePortfolio.ts             # SWR hook — portfolio state (W3)
│
├── proxy.ts                        # Clerk auth proxy — protect dashboard routes (Next.js 16)
├── next.config.ts                  # Next.js config — env, rewrites (W1)
├── tailwind.config.ts              # Tailwind config + shadcn/ui preset (W1)
├── tsconfig.json                   # TypeScript config (W1)
├── package.json                    # Dependencies (W1)
└── .env.local                      # Local env vars — gitignored (W1)
```

---

## `apps/api/` — FastAPI Backend

```
apps/api/
├── main.py                         # App factory — create_app(), startup hooks (W1)
├── config.py                       # Settings — Pydantic BaseSettings, env loading (W1)
├── deps.py                         # FastAPI dependencies — DB, Redis, auth (W1)
│
├── routers/
│   ├── __init__.py
│   ├── signals.py                  # POST /signals — generate ML signal (W1)
│   ├── portfolio.py                # POST /portfolio/rebalance (W3)
│   ├── backtest.py                 # POST /backtest/run (W3)
│   ├── keys.py                     # GET/POST/DELETE /keys — API key management (W2)
│   ├── usage.py                    # GET /usage — billing period usage summary (W2)
│   └── health.py                   # GET /health, GET /ready (W1)
│
├── models/
│   ├── __init__.py
│   ├── signal.py                   # SignalRequest, SignalResponse Pydantic models (W1)
│   ├── portfolio.py                # PortfolioRequest, RebalanceResponse (W3)
│   ├── backtest.py                 # BacktestRequest, BacktestResult (W3)
│   └── user.py                     # APIKey, UsageSummary (W2)
│
├── ml/
│   ├── __init__.py
│   ├── pipeline.py                 # Main signal pipeline — orchestrates steps (W1)
│   ├── data.py                     # Equity OHLCV via unified adapter (Alpaca → Tiingo) + feature prep (W1)
│   ├── features.py                 # Feature vector construction (W2)
│   ├── inference.py                # Load model + run prediction (W1)
│   ├── sentiment.py                # FinBERT sentiment → feature (W3)
│   └── models/
│       ├── __init__.py
│       ├── base.py                 # Abstract BaseModel interface (W1)
│       ├── lstm.py                 # LSTM price predictor (W2)
│       ├── ensemble.py             # Random Forest + XGBoost ensemble (W2)
│       └── quantum_hybrid.py      # QSVC + classical ensemble (W3)
│
├── quantum/
│   ├── __init__.py
│   ├── portfolio_optimizer.py      # QAOA + CVXPY portfolio optimization (W3)
│   ├── qubo_solver.py              # QUBO problem setup + D-Wave/simulator solve (W3)
│   └── circuits.py                 # PennyLane circuit definitions (W3)
│
├── db/
│   ├── __init__.py
│   ├── connection.py               # SQLAlchemy async engine + session factory (W1)
│   ├── models.py                   # ORM models — User, APIKey, UsageLog, Signal (W1)
│   └── queries.py                  # Typed query helpers (W2)
│
├── cache/
│   ├── __init__.py
│   └── redis.py                    # Redis client + typed get/set/invalidate helpers (W1)
│
├── billing/
│   ├── __init__.py
│   ├── stripe.py                   # Stripe metering — record_usage(), create_customer() (W2)
│   └── limits.py                   # Rate limit checks per plan tier (W2)
│
├── middleware/
│   ├── __init__.py
│   ├── auth.py                     # API key extraction + validation middleware (W1)
│   ├── rate_limit.py               # Redis sliding window rate limiter (W1)
│   └── logging.py                  # Structured request/response logging (W2)
│
├── tests/
│   ├── conftest.py                 # pytest fixtures — test DB, mock Redis, test client (W1)
│   ├── test_signals.py             # Signal endpoint — happy path + edge cases (W1)
│   ├── test_auth.py                # API key validation (W2)
│   ├── test_rate_limit.py          # Rate limiting behavior (W2)
│   ├── test_portfolio.py           # Portfolio optimization (W3)
│   └── test_ml/
│       ├── test_pipeline.py        # Signal pipeline unit tests (W2)
│       └── test_features.py        # Feature engineering tests (W2)
│
├── scripts/
│   ├── train_models.py             # Offline model training script (W2)
│   ├── backfill_signals.py         # Populate historical signal cache (W3)
│   └── seed_db.py                  # Seed dev DB with test data (W1)
│
├── requirements.txt                # Python deps — pinned versions (W1)
├── requirements-dev.txt            # Dev deps — pytest, black, ruff (W1)
├── Dockerfile                      # FastAPI container (W1)
├── pyproject.toml                  # Black + Ruff config (W1)
└── .env                            # Local env vars — gitignored (W1)
```

---

## `packages/db/` — Shared Database

```
packages/db/
├── migrations/
│   ├── 001_initial_schema.sql      # Users, API keys, usage logs (W1)
│   ├── 002_timescaledb.sql         # Convert signal_history to hypertable (W1)
│   ├── 003_billing_events.sql      # Stripe billing event log (W2)
│   └── 004_portfolio_snapshots.sql # Portfolio state history (W3)
├── schema.sql                      # Full schema — generated from migrations (W1)
└── README.md                       # How to run migrations (W1)
```

---

## `packages/types/` — Shared TypeScript Types

```
packages/types/
├── index.ts                        # Re-exports everything (W1)
├── signal.ts                       # Signal, SignalRequest, SignalResponse (W1)
├── user.ts                         # User, Plan, APIKey (W1)
├── billing.ts                      # UsageSummary, BillingEvent (W2)
└── portfolio.ts                    # Holding, RebalanceResult (W3)
```

---

## Root Config Files

```
sigma/
├── docker-compose.yml              # Local: postgres + timescaledb + redis (W1)
├── docker-compose.prod.yml         # Prod parity: same services, prod env vars (W1)
├── .env.example                    # Documented env var template (W1)
├── .gitignore                      # node_modules, .env, __pycache__, *.pyc, .next (W1)
├── Makefile                        # Shortcuts (W1)
└── README.md                       # Project overview + quick start (W1)
```

---

## Build Order by Week

### Week 1 — Skeleton (get one endpoint live and billing)
```
sigma/                              # Root setup
docker-compose.yml                  # Local dev environment
.env.example                        # All vars documented
Makefile                            # make dev, make test

apps/api/
  main.py                           # FastAPI app factory
  config.py                         # Settings
  deps.py                           # DB + Redis deps
  routers/health.py                 # GET /health
  routers/signals.py                # POST /signals — MVP endpoint
  models/signal.py                  # Request/response types
  ml/pipeline.py                    # Signal pipeline skeleton
  ml/data.py                        # Alpaca/Tiingo equity bars + feature prep
  ml/inference.py                   # Model load + predict
  db/connection.py                  # DB engine
  db/models.py                      # ORM models
  cache/redis.py                    # Redis client
  middleware/auth.py                # API key middleware
  middleware/rate_limit.py          # Rate limiter
  tests/conftest.py                 # Test fixtures
  tests/test_signals.py             # Signal tests
  requirements.txt
  Dockerfile

packages/db/
  migrations/001_initial_schema.sql
  schema.sql

apps/web/
  app/layout.tsx                    # Root + Clerk provider
  app/page.tsx                      # Landing page
  proxy.ts                          # Auth proxy (replaces middleware.ts in Next 16)
  lib/utils.ts
  lib/clerk.ts
  components/marketing/Hero.tsx
  components/marketing/PricingCard.tsx
  app/(marketing)/pricing/page.tsx
  app/(auth)/sign-in/.../page.tsx
  app/(auth)/sign-up/.../page.tsx
  tailwind.config.ts
  next.config.ts
  package.json
```

### Week 2 — Auth, billing, dashboard
```
apps/api/
  routers/keys.py                   # API key CRUD
  routers/usage.py                  # Usage summary
  billing/stripe.py                 # Stripe metering
  billing/limits.py                 # Plan tier limits
  middleware/logging.py             # Structured logs
  db/queries.py                     # Query helpers
  scripts/train_models.py           # Offline training
  tests/test_auth.py
  tests/test_rate_limit.py
  tests/test_ml/test_pipeline.py

packages/db/
  migrations/002_timescaledb.sql
  migrations/003_billing_events.sql

apps/web/
  api/webhooks/stripe.ts            # Stripe webhooks
  app/(dashboard)/layout.tsx        # Dashboard shell
  app/(dashboard)/dashboard/page.tsx
  app/(dashboard)/signals/page.tsx
  app/(dashboard)/api-keys/page.tsx
  app/(dashboard)/billing/page.tsx
  components/layout/Sidebar.tsx
  components/layout/Header.tsx
  components/signals/SignalCard.tsx
  components/signals/SignalChart.tsx
  components/signals/SignalForm.tsx
  components/billing/UsageMeter.tsx
  lib/stripe.ts
  lib/api.ts
  hooks/useSignal.ts
  hooks/useUsage.ts
```

### Week 3 — Portfolio optimizer + quantum
```
apps/api/
  routers/portfolio.py
  routers/backtest.py
  models/portfolio.py
  models/backtest.py
  quantum/portfolio_optimizer.py
  quantum/qubo_solver.py
  quantum/circuits.py
  ml/models/lstm.py
  ml/models/ensemble.py
  ml/models/quantum_hybrid.py
  ml/sentiment.py
  scripts/backfill_signals.py
  tests/test_portfolio.py

packages/db/
  migrations/004_portfolio_snapshots.sql

apps/web/
  app/(dashboard)/signals/[ticker]/page.tsx
  app/(dashboard)/portfolio/page.tsx
  components/signals/SignalHistory.tsx
  components/portfolio/HoldingsInput.tsx
  components/portfolio/AllocationChart.tsx
  components/portfolio/RebalanceOutput.tsx
  hooks/usePortfolio.ts
```

### Week 4 — Docs, polish, launch
```
apps/web/
  app/(marketing)/docs/page.tsx
  app/(marketing)/docs/[slug]/page.tsx
  components/layout/Footer.tsx
  components/marketing/FeatureGrid.tsx
```
