# SIGMA — Quick Start

> From zero to running local dev environment in under 30 minutes.

---

## Prerequisites

```bash
# Verify installed:
node --version        # >= 20.x
python --version      # >= 3.11
docker --version      # >= 24.x
git --version

# Install if missing:
# Node:   https://nodejs.org
# Python: https://python.org
# Docker: https://docker.com/get-started
```

---

## 1. Clone + Setup

```bash
git clone https://github.com/YOUR_USERNAME/sigma.git
cd sigma
cp .env.example apps/api/.env
cp .env.example apps/web/.env.local
# Then open both files and fill in at minimum the keys listed below.
```

Fill in at minimum these vars before continuing:
- `CLERK_SECRET_KEY` + `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` (get from dashboard.clerk.com)
- `STRIPE_SECRET_KEY` (get from dashboard.stripe.com — test mode is fine)

---

## 2. Start Local Services

```bash
# Start Postgres (with TimescaleDB) + Redis
docker compose up -d

# Verify all healthy:
docker compose ps
```

Expected output:
```
NAME                STATUS
sigma-postgres-1    Up (healthy)
sigma-redis-1       Up
```

---

## 3. Run Database Migrations

```bash
make migrate
```

The Makefile streams each file from `packages/db/migrations/` into the running
Postgres container (mounted read-only at `/migrations`). To apply them manually:

```bash
docker compose exec -T postgres psql -U postgres -d sigma -f /migrations/001_initial_schema.sql
docker compose exec -T postgres psql -U postgres -d sigma -f /migrations/002_timescaledb.sql
docker compose exec -T postgres psql -U postgres -d sigma -f /migrations/003_billing_events.sql
```

---

## 4. Start FastAPI Backend

```bash
cd apps/api

# Create virtualenv (first time only)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Seed dev data (creates test user + API key)
python scripts/seed_db.py

# Start dev server
uvicorn main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/health` → `{"status":"ok"}`

API docs: http://localhost:8000/docs (FastAPI auto-generated Swagger)

---

## 5. Start Next.js Frontend

```bash
cd apps/web

# Install dependencies (first time only)
npm install

# Start dev server
npm run dev
```

Open: http://localhost:3000

---

## 6. Run Tests

```bash
# Backend
cd apps/api
pytest -v

# Frontend (type check)
cd apps/web
npm run type-check
```

---

## 7. Make Your First API Call

After seeding the DB, a test API key is printed to the console.

```bash
# Using the test key printed by seed_db.py:
curl -X POST http://localhost:8000/signals \
  -H "Authorization: Bearer sk_test_YOUR_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "timeframe": "daily"}'
```

Expected response:
```json
{
  "ticker": "AAPL",
  "timeframe": "daily",
  "signal": "BUY",
  "confidence": 0.7234,
  "predicted_return": 0.0187,
  "model_version": "v1.0",
  "cached": false,
  "timestamp": "2026-04-20T14:32:00Z"
}
```

---

## 8. Useful Commands

```bash
# Makefile shortcuts (run from repo root):
make dev          # Start all services + both servers
make test         # Run all tests
make migrate      # Run pending migrations
make seed         # Seed dev database
make lint         # Run ruff (Python) + eslint (TypeScript)
make format       # Run black (Python) + prettier (TypeScript)
make logs         # Tail all Docker logs
make clean        # Stop Docker + remove volumes (WARNING: deletes data)
```

---

## Common Issues

**`docker compose up` fails — port already in use**
```bash
# Find what's using port 5432:
lsof -i :5432
# Kill it or change the port in docker-compose.yml
```

**`ImportError: No module named 'pennylane'`**
```bash
pip install pennylane qiskit qiskit-ibm-runtime
```

**Clerk auth redirect loops**
- Confirm `NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in` matches your actual route
- Clear browser cookies for localhost:3000

**Stripe webhooks not firing locally**
```bash
# Install Stripe CLI and forward to local:
stripe listen --forward-to localhost:3000/api/webhooks/stripe
```
