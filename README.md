# SIGMA

**ML-powered trading signal API with quantum-hybrid portfolio optimization.**

SIGMA is an API-first platform that generates institutional-grade trading signals using ensemble ML models and quantum-inspired portfolio optimization — served as a REST API with usage-based billing, a real-time dashboard, and a digital product storefront.

Built for engineers. No sales calls. No minimums. Pay per call.

---

## What It Does

| Capability | How |
|---|---|
| Trading signals | ML ensemble (LSTM + Random Forest + XGBoost) trained on OHLCV + 130 technical indicators |
| Sentiment overlay | FinBERT fine-tuned on financial news and Twitter |
| Portfolio optimization | CVXPY mean-variance + QAOA via PennyLane / Qiskit |
| Backtesting | Vectorized strategy simulation with Sharpe, drawdown, win rate |
| API monetization | Stripe usage-based metering — pay per call, no minimum |
| Digital products | Code templates and trained models sold via Gumroad |

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  Next.js 15  (Vercel)                        │
│  Landing · Dashboard · Docs · API Keys       │
└──────────────┬───────────────────────────────┘
               │ REST
┌──────────────▼───────────────────────────────┐
│  Vercel Functions  (TypeScript)              │
│  Auth · Rate limiting · Stripe metering      │
└──────────────┬───────────────────────────────┘
               │
       ┌───────┴────────┐
       │                │
┌──────▼──────┐  ┌──────▼──────┐
│  FastAPI    │  │  PostgreSQL │
│  (Railway)  │  │+ TimescaleDB│
│             │  │  + Redis    │
│  ML · Quantum│  │  (Railway)  │
│  Signals    │  └─────────────┘
└─────────────┘
```

Two services. The API gateway (TypeScript, Vercel) handles auth and billing. The ML backend (Python, Railway) handles signal generation, portfolio optimization, and quantum circuits. Each can be deployed and scaled independently.

---

## Stack

**Frontend** — Next.js 15, React 19, Tailwind CSS, shadcn/ui, Recharts

**Backend** — FastAPI, Pydantic v2, SQLAlchemy (async)

**ML** — PyTorch, scikit-learn, pandas-ta, yfinance, HuggingFace Transformers (FinBERT)

**Quantum** — Qiskit, PennyLane, CVXPY

**Data** — PostgreSQL 15 + TimescaleDB extension, Redis 7

**Auth** — Clerk (email + GitHub OAuth, API key management)

**Payments** — Stripe Billing (usage metering + subscriptions), Gumroad (digital products)

**Deploy** — Vercel (frontend), Railway (backend + database)

**Observability** — Sentry, Langfuse, pytest

---

## Getting Started

### Prerequisites

```bash
node --version    # >= 20.x
python --version  # >= 3.11
docker --version  # >= 24.x
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

### Core endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health — no auth |
| `POST` | `/signals` | Generate ML trading signal |
| `GET` | `/signals/{ticker}/history` | Historical signals for a ticker |
| `POST` | `/portfolio/rebalance` | Optimize portfolio allocation |
| `POST` | `/backtest/run` | Backtest a strategy on historical data |
| `GET` | `/keys` | List API keys |
| `POST` | `/keys` | Create API key |
| `DELETE` | `/keys/{id}` | Revoke API key |
| `GET` | `/usage` | Current billing period usage |

### Rate limits

| Plan | Calls / day | Burst / minute |
|------|-------------|----------------|
| Free | 100 | 10 |
| Pro | 10,000 | 200 |
| Enterprise | Unlimited | 2,000 |

Full API reference: [`docs/05_API_REFERENCE.md`](./docs/05_API_REFERENCE.md)

---

## Project Structure

```
sigma/
├── apps/
│   ├── web/          # Next.js — landing, dashboard, docs, billing
│   └── api/          # FastAPI — signals, ML, quantum, portfolio
├── packages/
│   ├── db/           # SQL migrations + schema
│   └── types/        # Shared TypeScript types
├── docker-compose.yml
├── Makefile
└── .env.example
```

Full structure with every file documented: [`docs/02_PROJECT_STRUCTURE.md`](./docs/02_PROJECT_STRUCTURE.md)

---

## Development Commands

```bash
make dev        # Start all services and both dev servers
make test       # Run backend (pytest) + frontend (type-check)
make migrate    # Run pending SQL migrations
make seed       # Seed dev database with test data
make lint       # ruff (Python) + eslint (TypeScript)
make format     # black (Python) + prettier (TypeScript)
make logs       # Tail all Docker container logs
make clean      # Stop Docker and remove volumes
```

---

## Documentation

| File | Contents |
|------|----------|
| [`docs/00_QUICKSTART.md`](./docs/00_QUICKSTART.md) | Step-by-step local setup |
| [`docs/01_TECH_STACK.md`](./docs/01_TECH_STACK.md) | Stack tiers — essential, core, nice-to-have, later |
| [`docs/02_PROJECT_STRUCTURE.md`](./docs/02_PROJECT_STRUCTURE.md) | Every file, its purpose, and build order |
| [`docs/03_ENV_VARS.md`](./docs/03_ENV_VARS.md) | All environment variables and where to get them |
| [`docs/04_DATABASE_SCHEMA.md`](./docs/04_DATABASE_SCHEMA.md) | SQL migrations and schema design decisions |
| [`docs/05_API_REFERENCE.md`](./docs/05_API_REFERENCE.md) | Full endpoint reference with request/response shapes |
| [`docs/06_ROADMAP.md`](./docs/06_ROADMAP.md) | Week-by-week build plan with acceptance criteria |

---

## Deployment

### Backend (Railway)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Link project and deploy
railway login
railway link
railway up
```

Railway auto-injects `DATABASE_URL` and `REDIS_URL` when services are attached. Set all other env vars via the Railway dashboard or:

```bash
railway variables set --from-env apps/api/.env
```

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

# IBM Quantum (optional for local dev — uses simulator by default)
IBM_QUANTUM_TOKEN=
IBM_QUANTUM_BACKEND=ibm_brisbane
```

Full variable reference: [`docs/03_ENV_VARS.md`](./docs/03_ENV_VARS.md)

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

- [x] Core signal generation API
- [x] Usage-based Stripe billing
- [x] API key management dashboard
- [x] Portfolio rebalancer (CVXPY + QAOA)
- [x] Strategy backtesting engine
- [ ] FinBERT sentiment overlay (Month 2)
- [ ] Replicate model hosting for inference revenue (Month 2)
- [ ] WebSocket streaming signals (Month 3)
- [ ] Multi-asset correlation signals (Month 3)
- [ ] Enterprise SLA + dedicated endpoints (Month 4)

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