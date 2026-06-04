# SIGMA

[![CI](https://github.com/Quantum-Global-Group/sigma/actions/workflows/ci.yml/badge.svg)](https://github.com/Quantum-Global-Group/sigma/actions/workflows/ci.yml)

**ML-powered trading signal API with quantum-hybrid portfolio optimization, multi-asset coverage (equity, crypto, forex, options), and a live paper-trading worker.**

> SIGMA is an API-first platform that generates institutional-grade trading signals using ensemble ML models and quantum-inspired portfolio optimization — served as a REST API with usage-based billing, a real-time dashboard, and a digital product storefront. A separate worker service runs the merged razorBill strategy stack against the house book in paper mode across venue adapters (Alpaca equities, Coinbase crypto, OANDA forex, Moomoo options via local OpenD).

Built for engineers. No sales calls. No minimums. Pay per call.

---

## Current status

**Milestone:** M1 — internal alpha (paper). Core build plus audit/reporting slice
(2026-06) are shipped; what remains is **operational** — Fly deploy, migrations
001–013 on prod, 2+ weeks paper observation, weekly strategy review, then M2 decision.

**Alpha focus:** equity-first on Alpaca paper, with the trained `ensemble_v1.0.pkl`
wired into the worker (not the heuristic fallback). Crypto ranking model follows
once the equity loop is observed.

| Area | State |
|---|---|
| **Core API** | Signals, portfolio optimizer, backtesting, API keys, Stripe metering |
| **Worker loop** | Per-tick fetch → combiner → risk → executor → persisted orders/positions + `audit_records`; startup book reconciliation |
| **Equity** | Alpaca paper executor; Alpaca → Tiingo data; trained ensemble shipped in worker image |
| **Crypto** | Coinbase candles + Advanced Trade adapter; RankingModel trainable via `make train-ranking` |
| **Forex** | OANDA practice executor (cloud REST — runs on Fly alongside other classes) |
| **Options** | Moomoo/OpenD paper executor — **local/VPS worker only** (OpenD can't run on Fly) |
| **Audit & reports** | `audit_records` for all asset classes; strategy performance API + `/strategies` dashboard |
| **ML ops** | Per-family MLflow experiments; promotion reports; pgvector embeddings (migration 012) |
| **Deploy** | Fly.io configs for `sigma-api` + `sigma-worker`; per-class runbooks in `docs/DEPLOY_*.md` |
| **Validation** | Offline E2E smoke (`make e2e`, migrations `001–013`); OANDA practice in `docs/E2E_VALIDATION.md` |
| **Go-live** | Human-owned paper→real procedure with three independent locks — `docs/GO_LIVE.md` |
| **CI** | GitHub Actions — pytest + npm type-check on push/PR |

**Next up:** Fly deploy ([`docs/DEPLOY_EQUITY.md`](./docs/DEPLOY_EQUITY.md)), 2+ weeks paper,
weekly `/strategies` review, enable pgvector embed job when DGX ready, then M2 beta.

Single source of truth for milestones and sprints: [`docs/ROADMAP.md`](./docs/ROADMAP.md).

---

## Reading Order

1. [Current status](#current-status)
2. [What It Does](#what-it-does)
3. [Architecture](#architecture)
4. [Stack](#stack)
5. [Getting Started](#getting-started)
6. [API](#api)
7. [Project Structure](#project-structure)
8. [Development Commands](#development-commands)
9. [Documentation](#documentation)
10. [Deployment](#deployment)
11. [Environment Variables](#environment-variables)
12. [Pricing](#pricing)
13. [Roadmap](#roadmap)

---

## Audience

| Audience | Start Here |
| --- | --- |
| New contributor | [Getting Started](#getting-started), [Project Structure](#project-structure) |
| API consumer | [API](#api), [`05_API_REFERENCE.md`](./05_API_REFERENCE.md) |
| ML engineer | [`docs/MODELS.md`](./docs/MODELS.md), [Stack](#stack) |
| Operator / deployer | [Deployment](#deployment), [`DEPLOY.md`](./DEPLOY.md), [`docs/RUNBOOK_WORKER.md`](./docs/RUNBOOK_WORKER.md) |
| Planner | [Roadmap](#roadmap), [`docs/ROADMAP.md`](./docs/ROADMAP.md) |

---

## What It Does

| Capability | How |
|---|---|
| Trading signals (equity + crypto) | ML ensemble (LSTM + Random Forest + XGBoost) for equities; razorBill RankingModel (LightGBM / XGBoost / SGD) for crypto. Both behind a single `MarketAdapter` abstraction. Forex/options use the combiner + venue-specific executors. |
| Live worker loop | Long-running `apps/worker/` service: per-tick fetch → features → per-asset strategy combiner → risk + sizing → executor → persisted orders / positions / exit state |
| Sentiment overlay | Pluggable providers — FinBERT, LangExtract (with local Ollama), or hybrid. Selected via `SENTIMENT_PROVIDER`. |
| Portfolio optimization | CVXPY mean-variance + QAOA via PennyLane / Qiskit |
| Backtesting | Vectorized strategy simulation with Sharpe, drawdown, win rate |
| Execution adapters | Paper (size-aware slippage, partial fills, latency jitter); Alpaca (equity), Coinbase Advanced Trade (crypto), OANDA (forex), Moomoo/OpenD (options, local only) |
| API monetization | Stripe usage-based metering — pay per call, no minimum. Worker traffic uses `X-Internal-Secret` to bypass billing while still logging usage. |
| Digital products | Code templates and trained models sold via Gumroad |

---

## Architecture

Three services. The API gateway (TypeScript, Vercel) handles auth and billing. The ML backend (Python, Fly.io) handles signal generation, portfolio optimization, and quantum circuits. The worker (Python, Fly.io) runs the per-tick trading cycle and reads/writes positions, orders, and exit state through the same Postgres. Options run on a separate local/VPS worker next to Moomoo OpenD, sharing the same database. Each service can be deployed and scaled independently.

```mermaid
flowchart TB
  subgraph edge [Vercel]
    WEB["Next.js 16 — Landing · Dashboard · Docs · Positions · Orders · Strategies · Billing"]
    GW["Vercel Functions (TypeScript) — Auth · Rate limiting · Stripe metering"]
  end
  subgraph fly [Fly.io]
    API["FastAPI — ML · Quantum · Signals"]
    WORKER["apps/worker — live tick loop (equity · crypto · forex)"]
  end
  subgraph lab [Local / VPS]
    OPT["options worker — Moomoo OpenD"]
  end
  subgraph data [Data — Timescale Cloud / Upstash]
    PG[("PostgreSQL + TimescaleDB")]
    REDIS[("Redis")]
  end
  WEB --> GW
  GW -->|REST| API
  GW -->|"X-Internal-Secret"| API
  API <-->|"X-Internal-Secret"| WORKER
  API --> PG
  API --> REDIS
  WORKER --> PG
  WORKER --> REDIS
  OPT --> PG
  OPT --> REDIS
```

---

## Stack

**Frontend** — Next.js 16, React 19, Tailwind CSS, shadcn/ui, Recharts

**Backend** — FastAPI, Pydantic v2, SQLAlchemy (async)

**ML** — PyTorch, scikit-learn, LightGBM, XGBoost, pandas-ta, Tiingo/Alpaca, HuggingFace Transformers (FinBERT)

**Quantum** — Qiskit, PennyLane, CVXPY

**Crypto market data + execution** — Coinbase Exchange (public candles), Coinbase Advanced Trade (live orders, sandbox + prod)

**Data** — PostgreSQL 15 + TimescaleDB extension, Redis 7

**Auth** — Clerk (email + GitHub OAuth, API key management)

**Payments** — Stripe Billing (usage metering + subscriptions), Gumroad (digital products)

**Deploy** — Vercel (frontend), Fly.io (api + worker), Timescale Cloud or Crunchy Bridge (Postgres + TimescaleDB), Upstash (Redis)

**Observability** — Sentry, Langfuse, pytest

---

## Getting Started

### Prerequisites

```bash
node --version    # >= 20.x
python --version  # >= 3.12 (pandas-ta requires it; Dockerfile + CI use 3.12)
docker --version  # >= 24.x
```

### Setup flow

```mermaid
flowchart LR
  A[Clone + configure .env] --> B[docker compose up -d]
  B --> C[make migrate]
  C --> D[make seed]
  D --> E[Start FastAPI :8000]
  E --> F[Start Next.js :3000]
  F --> G[First API call]
```

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/sigma.git
cd sigma

cp .env.example apps/api/.env
cp .env.example apps/web/.env.local
```

Open both `.env` files and set at minimum:

```env
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
```

### 2. Start local services

```bash
docker compose up -d   # Postgres + TimescaleDB + Redis
make migrate           # Run all SQL migrations
make seed              # Create a test user and API key
```

### 3. Start the backend

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Swagger docs available at `http://localhost:8000/docs`

### 4. Start the frontend

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`

### 5. Make your first API call

The seed script prints a test API key. Use it:

```bash
curl -X POST http://localhost:8000/signals \
  -H "Authorization: Bearer sk_test_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "timeframe": "daily"}'
```

```json
{
  "ticker": "AAPL",
  "timeframe": "daily",
  "signal": "BUY",
  "confidence": 0.7821,
  "predicted_return": 0.0234,
  "model_version": "v1.0",
  "cached": false,
  "timestamp": "2026-04-20T14:32:00Z"
}
```

---

## API

Base URL: `https://api.sigma.dev` | Local: `http://localhost:8000`

All endpoints require `Authorization: Bearer YOUR_API_KEY` unless noted.

### Request lifecycle

```mermaid
sequenceDiagram
  participant Client
  participant Gateway as Vercel Gateway
  participant API as FastAPI
  participant Redis
  participant Meter as Stripe
  Client->>Gateway: POST /signals (Bearer key)
  Gateway->>Redis: validate key + rate limit
  Gateway->>API: forward request
  API->>Redis: signal cache lookup
  API->>API: ML pipeline (on miss)
  API-->>Gateway: signal payload
  Gateway->>Meter: record usage (customer keys only)
  Gateway-->>Client: 200 signal
```

### Core endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health — no auth |
| `POST` | `/signals` | Generate ML trading signal — accepts `asset_class: "equity" \| "crypto"` (default `equity`) |
| `GET` | `/signals/{ticker}/history` | Historical signals for a ticker |
| `POST` | `/portfolio/rebalance` | Optimize portfolio allocation |
| `POST` | `/backtest/run` | Backtest a strategy on historical data |
| `GET` | `/positions` | House-book positions (worker-managed); filter by `asset_class` (`equity` \| `crypto` \| `forex` \| `option`), `open_only` |
| `GET` | `/orders` | Recent fills / orders; filter by `asset_class`, `symbol` |
| `GET` | `/execution/status` | Current executor mode + worker cadence |
| `POST` | `/execution/run_cycle` | Trigger a single worker tick on demand (requires `X-Internal-Secret`) |
| `GET` | `/keys` | List API keys |
| `POST` | `/keys` | Create API key |
| `DELETE` | `/keys/{id}` | Revoke API key |
| `GET` | `/usage` | Current billing period usage |
| `GET` | `/strategies/performance` | Per-strategy stats from labeled `signal_history` (`asset_class`, `period`) |
| `GET` | `/strategies/performance/report` | Same + markdown `summary` (default `period=7d`) |
| `GET` | `/models/promotions/{id}/report` | Candidate vs incumbent promotion comparison |

### Rate limits

| Plan | Calls / day | Burst / minute |
|------|-------------|----------------|
| Free | 100 | 10 |
| Pro | 10,000 | 200 |
| Enterprise | Unlimited | 2,000 |

Full API reference: [`05_API_REFERENCE.md`](./05_API_REFERENCE.md)

---

## Project Structure

```
sigma/
├── apps/
│   ├── web/          # Next.js — landing, dashboard, docs, billing, positions, orders, execution
│   ├── api/          # FastAPI — signals, ML, quantum, portfolio, markets, execution adapters, risk
│   └── worker/       # Long-running asyncio service — per-tick trading cycle (paper + venue adapters)
├── packages/
│   ├── db/           # SQL migrations 001–013 + schema
│   └── types/        # Shared TypeScript types — barrel `@sigma/types`
├── .github/workflows/  # CI (pytest + npm type-check on push/PR)
├── docs/
│   ├── ROADMAP.md        # Milestones + sprints + backlog (single source of truth)
│   ├── MODELS.md         # Features, registry, training, worker model wiring
│   ├── E2E_VALIDATION.md # Offline smoke + OANDA practice + deploy validation
│   ├── GO_LIVE.md        # Staged paper→real procedure (human-owned)
│   ├── DEPLOY_EQUITY.md  # Equity (Alpaca paper) Fly deploy runbook
│   ├── DEPLOY_FOREX.md   # Forex (OANDA practice) Fly overlay
│   ├── DEPLOY_OPTIONS.md # Options (Moomoo/OpenD) local/VPS overlay
│   └── …
├── 00_QUICKSTART.md … 05_API_REFERENCE.md  # Numbered setup/API docs (repo root)
├── DEPLOY.md           # General production deploy runbook
├── docker-compose.yml  # postgres + redis + worker (under --profile worker)
├── Makefile
└── .env.example
```

Full structure with every file documented: [`02_PROJECT_STRUCTURE.md`](./02_PROJECT_STRUCTURE.md)

---

## Development Commands

```bash
make dev            # Start all services and both dev servers
make test           # Run backend (pytest) + frontend (type-check)
make migrate        # Run pending SQL migrations
make seed           # Seed dev database with test data
make lint           # ruff (Python) + eslint (TypeScript)
make format         # black (Python) + prettier (TypeScript)
make logs           # Tail all Docker container logs
make clean          # Stop Docker and remove volumes

make worker         # Build + run the live trading worker (Docker --profile worker)
make worker-local   # Run the worker directly against local Postgres + Redis
make train-ranking  # Fetch Coinbase history + fit the crypto RankingModel artifact
make e2e            # Offline E2E smoke — real Postgres, synthetic market, paper executor
make e2e-down       # Stop E2E containers (data persists until make clean)
```

---

## Documentation

| File | Contents |
|------|----------|
| [`00_QUICKSTART.md`](./00_QUICKSTART.md) | Step-by-step local setup |
| [`01_TECH_STACK.md`](./01_TECH_STACK.md) | Stack tiers — essential, core, nice-to-have, later |
| [`02_PROJECT_STRUCTURE.md`](./02_PROJECT_STRUCTURE.md) | Every file, its purpose, and build order |
| [`03_ENV_VARS.md`](./03_ENV_VARS.md) | All environment variables and where to get them |
| [`04_DATABASE_SCHEMA.md`](./04_DATABASE_SCHEMA.md) | SQL migrations 001–004 + pointer to 005–012 supplement |
| [`docs/DATABASE_SCHEMA.md`](./docs/DATABASE_SCHEMA.md) | Migrations 005–012 tables (trading, audit, ML, pgvector) |
| [`05_API_REFERENCE.md`](./05_API_REFERENCE.md) | Full endpoint reference (signals + trading/ops) |
| [`docs/05_API_REFERENCE.md`](./docs/05_API_REFERENCE.md) | Index to canonical API ref (ROADMAP/docs links) |
| [`docs/RUNBOOK_WORKER.md`](./docs/RUNBOOK_WORKER.md) | Pause, stop, and restart the worker safely |
| [`docs/decisions/`](./docs/decisions/) | Architecture decision records (ADRs) |
| [`docs/ROADMAP.md`](./docs/ROADMAP.md) | Milestones, sprints, and backlog (single source of truth) |
| [`docs/MODELS.md`](./docs/MODELS.md) | Features, model registry, training, and worker model wiring |
| [`docs/E2E_VALIDATION.md`](./docs/E2E_VALIDATION.md) | Offline smoke, OANDA practice, deploy validation layers |
| [`docs/GO_LIVE.md`](./docs/GO_LIVE.md) | Staged paper→real procedure with approval gates |
| [`DEPLOY.md`](./DEPLOY.md) | General production deploy runbook |
| [`docs/DEPLOY_EQUITY.md`](./docs/DEPLOY_EQUITY.md) | Equity (Alpaca paper) Fly deploy runbook |
| [`docs/DEPLOY_FOREX.md`](./docs/DEPLOY_FOREX.md) | Forex (OANDA practice) Fly overlay |
| [`docs/DEPLOY_OPTIONS.md`](./docs/DEPLOY_OPTIONS.md) | Options (Moomoo/OpenD) local/VPS overlay |
| [`docs/M1_BRINGUP.md`](./docs/M1_BRINGUP.md) | M1 bring-up checklist — wire infra + brokers, flip off paper, observe |

---

## Deployment

For the full production deploy, webhook setup, migrations, load testing, and
launch checklist, see [DEPLOY.md](./DEPLOY.md). Per-asset-class overlays:
[DEPLOY_EQUITY.md](./docs/DEPLOY_EQUITY.md) · [DEPLOY_FOREX.md](./docs/DEPLOY_FOREX.md) ·
[DEPLOY_OPTIONS.md](./docs/DEPLOY_OPTIONS.md). Quick commands below.

### Backend (Fly.io)

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh
fly auth login

# Provision two apps from their fly.toml files
cd apps/api    && fly launch --copy-config --no-deploy --name sigma-api    && cd ../..
cd apps/worker && fly launch --copy-config --no-deploy --name sigma-worker && cd ../..

# Secrets (INTERNAL_SECRET, CLERK_*, STRIPE_*, COINBASE_*, DATABASE_URL, REDIS_URL)
fly secrets set -a sigma-api    DATABASE_URL=... REDIS_URL=... INTERNAL_SECRET=...
fly secrets set -a sigma-worker DATABASE_URL=... REDIS_URL=... INTERNAL_SECRET=... \
                                 COINBASE_API_KEY_NAME=... COINBASE_PRIVATE_KEY=...

# Deploy
cd apps/api && fly deploy
fly deploy -a sigma-worker --config apps/worker/fly.toml --dockerfile apps/worker/Dockerfile .
```

Postgres + Redis live with separate providers — Timescale Cloud or Crunchy Bridge for the timescaledb-extended Postgres (vanilla Fly Postgres doesn't ship the extension), Upstash for Redis. Full step-by-step in [DEPLOY.md](DEPLOY.md).

### Frontend (Vercel)

```bash
# Install Vercel CLI
npm install -g vercel

cd apps/web
vercel --prod
```

Set env vars in the Vercel dashboard under Project → Settings → Environment Variables.

### Stripe local webhook forwarding

```bash
stripe listen --forward-to localhost:3000/api/webhooks/stripe
```

### Load testing

Locust file at [tests/load_test.py](./tests/load_test.py). Point it at staging:

```bash
pip install locust
SIGMA_LOADTEST_BASE_URL=https://staging-api.sigma.dev \
SIGMA_LOADTEST_API_KEY=sk_test_... \
make load-test
```

### Gumroad bundles

```bash
make package-gumroad
# outputs: dist/gumroad/dashboard-template.zip and ml-boilerplate.zip
```

---

## Environment Variables

Required to run locally:

```env
# Clerk — dashboard.clerk.com
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...

# Stripe — dashboard.stripe.com
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Database (auto-set by Docker Compose locally)
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sigma
REDIS_URL=redis://localhost:6379

# Worker / live trading (only needed when running apps/worker)
INTERNAL_SECRET=change-me              # Worker uses this to call /signals
EXECUTOR_MODE=paper                    # paper | coinbase
WORKER_ASSET_CLASSES=equity            # comma-separated: crypto,equity,forex,option
COINBASE_API_KEY_NAME=                 # required when EXECUTOR_MODE=coinbase
COINBASE_PRIVATE_KEY=
COINBASE_SANDBOX=true

# Sentiment provider (optional)
SENTIMENT_PROVIDER=finbert             # finbert | langextract | ollama | hybrid | none
LX_MODEL_ID=mistral:7b-instruct        # only used when langextract/ollama selected
LX_MODEL_URL=http://127.0.0.1:11434

# IBM Quantum (optional for local dev — uses simulator by default)
IBM_QUANTUM_TOKEN=
IBM_QUANTUM_BACKEND=ibm_brisbane
```

Full variable reference: [`03_ENV_VARS.md`](./03_ENV_VARS.md)

---

## Pricing

| Plan | Price | Signals / day | Features |
|------|-------|---------------|---------|
| Free | $0 | 100 | Basic signals, daily timeframe |
| Pro | $99 / month | 10,000 | All timeframes, portfolio optimizer, backtesting, CSV export |
| Enterprise | Custom | Unlimited | Quantum backends, custom models, SLA, priority support |

Usage-based option: $0.01 per signal call — no subscription required.

---

## Roadmap

The **code build for the internal alpha is effectively complete** — what remains for M1 is operational (run the Fly deploy, then observe). [`docs/ROADMAP.md`](./docs/ROADMAP.md) is the single source of truth for milestones, sprints, and backlog.

```mermaid
flowchart LR
  BUILT["✅ Built — alpha code complete"] --> M1["🚧 M1 — Internal alpha (deploy + observe)"]
  M1 --> M2["⬜ M2 — Beta (multi-tenant paper)"]
  M2 --> M3["⬜ M3 — Production (sandbox → live)"]
```

### ✅ Built (shipped on `main`)

- [x] Core signal generation API — equity, crypto, forex behind one `MarketAdapter`
- [x] Usage-based Stripe billing + API key management dashboard
- [x] Portfolio rebalancer (CVXPY + QAOA) + strategy backtesting engine
- [x] **razorBill + tradeFlux merge** — crypto signals, multi-strategy combiner, Alpaca equity execution, advanced exits, dynamic universe
- [x] **Live worker loop** — paper executor, venue adapters (Coinbase, Alpaca, OANDA, Moomoo), ExitState persistence, rebuy cooldown, startup book reconciliation
- [x] **Trained equity ensemble** wired into worker (`ensemble_v1.0.pkl` baked into image)
- [x] **Self-evolution loop** — decision logging + outcome labeling (009), evaluate → human-gated promotion → champion (010), worker scheduler
- [x] **Alpha research foundation** — purged CV (`ml/cv.py`), triple-barrier labels, crypto meta-labeling, cost-aware net-edge gate
- [x] **Observability + ops** — worker Sentry, `/health/worker`, executor retry/backoff, Redis singleton lock, CI workflow
- [x] **Audit & strategy reporting** — `audit_records` parity; performance API; `/strategies` dashboard
- [x] **ML ops slice** — MLflow per-family experiments, promotion reports, pgvector embeddings (012), universe comparison CLI
- [x] **Deploy + validation docs** — Fly configs, per-class runbooks, E2E smoke (`make e2e`), go-live procedure
- [x] **Next.js 16** web upgrade

### 🚧 M1 — Internal alpha (current, operational)

- [ ] `fly deploy` `sigma-api` + `sigma-worker`; provision prod Postgres (Timescale Cloud) + Redis (Upstash); migrations 001–013
- [ ] Worker runs **2+ weeks unattended** on Fly; one healthy tick per cadence; orders/positions rows grow
- [ ] Trained crypto **RankingModel** artifact shipped (follows once the equity loop is observed)
- [ ] Daily signal log + weekly `/strategies` review; Sentry ≤1 unique exception/week
- [ ] M1 → M2 go/no-go decision (`docs/decisions/`)

### ⬜ M2 — Beta (paper, multi-tenant)

- [ ] Expose `/signals?asset_class=crypto` to Pro+; Stripe metering correctness audit (crypto vs equity, no internal traffic billed)
- [ ] Customer-facing web pages — remove plaintext API-key inputs, integrate Clerk session
- [ ] API reference for `/positions`, `/orders`, `/execution`; rate-limit fairness across asset classes; beta-invite flow

### ⬜ M3 — Production (sandbox → live)

- [ ] Staged go-live per [`docs/GO_LIVE.md`](./docs/GO_LIVE.md) — sandbox roundtrip, then live keys with **per-day notional cap**
- [ ] Risk circuit breaker (single switch to halt all worker buys); DR runbook (stop worker, reconcile positions, restart)

See [`docs/ROADMAP.md`](./docs/ROADMAP.md) for the full sprint plan and backlog.

---

## License

MIT — see [LICENSE](./LICENSE)

---

## Contributing

This is a solo-founder project in active development. Issues and PRs welcome.

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Run tests before pushing: `make test`
4. Open a pull request against `main`
