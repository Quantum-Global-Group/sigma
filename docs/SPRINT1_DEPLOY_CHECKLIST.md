# Sprint 1 — Deploy + first model train (execution checklist)

Operational steps to finish M1 Sprint 1 on Fly.io with the **equity** alpha path.
Code is ready; this doc is copy-paste commands for the operator machine (e.g. DGX).

**Source runbooks:** [`DEPLOY_EQUITY.md`](DEPLOY_EQUITY.md) (equity), [`DEPLOY.md`](../DEPLOY.md) (general infra).

---

## 0. Prerequisites

```bash
# From repo root
cd /path/to/sigma

# Python venv (local verification only)
cd apps/api && python -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ../..

# Fly CLI
curl -L https://fly.io/install.sh | sh
export PATH="$HOME/.fly/bin:$PATH"
fly auth login
fly auth whoami   # must print your Fly account

# psql client (migrations from laptop)
sudo apt-get install -y postgresql-client   # Debian/Ubuntu
```

**Accounts / keys** (see [`.env.example`](../.env.example)):

| Secret | Apps | Required for |
|--------|------|--------------|
| `INTERNAL_SECRET` | api + worker | service-to-service auth (must match) |
| `DATABASE_URL` | api + worker | Timescale Cloud Postgres (`postgresql+asyncpg://…?sslmode=require`) |
| `REDIS_URL` | api + worker | Upstash Redis (`rediss://…`) |
| `ALPACA_API_KEY`, `ALPACA_SECRET` | api + worker | equity execution + data |
| `TIINGO_API_KEY` | api + worker | equity OHLCV fallback |
| `SENTRY_DSN` | api + worker | worker tick exception alerts |
| `HUGGINGFACE_TOKEN` | api + worker | optional (FinBERT) |
| `CLERK_*`, `STRIPE_*` | api (+ web on Vercel) | auth/billing when web is deployed |

---

## 1. Local readiness (before Fly)

**DGX 24/7 worker:** from repo root, `make worker-local` (loads `apps/api/.env` — set `DATABASE_URL` to Tiger Cloud, `REDIS_URL` to Upstash, `WORKER_ASSET_CLASSES=equity`, plus Alpaca/Tiingo keys; local `docker compose` Postgres/Redis optional for dev-only).

```bash
cd apps/api

# Ensemble artifact present and loadable
ls -lh ml/saved_models/ensemble_v1.0.pkl
.venv/bin/python -c "from ml.models.registry import resolve; m=resolve('equity'); print(m)"

# Deploy-related tests
.venv/bin/pytest -v tests/test_worker_status.py tests/test_worker_tick.py \
  tests/test_experiment.py tests/test_ml/test_pipeline.py

# Optional: fresh ensemble train (needs Alpaca + Tiingo keys in env)
# PYTHONPATH=. python scripts/train_models.py --ensemble --asset-class equity
```

**Local migrations** (optional smoke — needs Docker):

```bash
cd ../..   # repo root
POSTGRES_HOST_PORT=5434 docker compose up -d postgres redis
for f in packages/db/migrations/*.sql; do
  docker compose exec -T postgres psql -U postgres -d sigma -v ON_ERROR_STOP=1 \
    -f "/migrations/$(basename "$f")"
done
```

> If port 5432/5433 is taken, set `POSTGRES_HOST_PORT=5434` (or another free port).

---

## 2. Point worker at equities

Edit and **commit** `apps/worker/fly.toml` `[env]`:

```toml
WORKER_ASSET_CLASSES = "equity"
EQUITY_EXECUTOR = "alpaca"
EQUITY_DATA_PROVIDERS = "alpaca,tiingo"
# Already set: ALPACA_PAPER="true", ALPACA_ALLOW_LIVE="false",
#              MODEL_DIR="/app/api/ml/saved_models"
```

---

## 3. Provision Fly apps (once)

**Current DGX apps (2026-06-02):** names `sigma-api` / `sigma-worker` are taken globally,
so this account uses:

| Role | Fly app name | Config |
|------|----------------|--------|
| API | `sigma-api-proud-tree-92` | `apps/api/fly.toml` (`app = …`) |
| Worker | `sigma-worker-proud-tree-92` | `apps/worker/fly.toml` |

Public URLs (after first deploy):

- API: `https://sigma-api-proud-tree-92.fly.dev`
- Worker: no public HTTP (logs via `fly logs`)

Set once in your shell:

```bash
export FLY_API_APP=sigma-api-proud-tree-92
export FLY_WORKER_APP=sigma-worker-proud-tree-92
export PATH="$HOME/.fly/bin:$PATH"
```

If reprovisioning from scratch:

```bash
fly apps create "$FLY_API_APP" --org personal
fly apps create "$FLY_WORKER_APP" --org personal
```

Equity worker env is committed in `2497aba` (`apps/worker/fly.toml`).

---

## 4. Postgres (Timescale Cloud) + Redis (Upstash)

### Timescale — you need a connection string, not an “API key”

Sigma stores **`DATABASE_URL`** on Fly (user + password + host). Sign up at
[Timescale Cloud](https://console.cloud.timescale.com) (hosted Postgres + TimescaleDB extension).
The [GitHub timescaledb repo](https://github.com/timescale/timescaledb) is the extension source — not where you get prod credentials.

**Step-by-step:** [`TIMESCALE_SETUP.md`](TIMESCALE_SETUP.md)

Summary:

1. Create a cloud service (free trial OK).
2. Enable `timescaledb` (+ `vector` if you want migration `012` / embeddings).
3. Copy the connection string → format as  
   `postgresql+asyncpg://USER:PASS@HOST:5432/tsdb?sslmode=require`
4. Set on both Fly apps in §5 below.

Local Docker Postgres (`docker compose`) is for **dev only** — Fly cannot use your DGX localhost URL.

### Upstash Redis

1. [upstash.com](https://upstash.com) → Create Redis database.
2. Copy **`REDIS_URL`** (`rediss://...` with TLS).
3. Set on both Fly apps in §5.

---

## 5. Set secrets

**Status:** both apps currently have **zero secrets** until you run this step.
Fill placeholders from Timescale Cloud, Upstash, Alpaca paper, Tiingo, Sentry.
See `.env.example` for the full key list.

```bash
export FLY_API_APP=sigma-api-proud-tree-92
export FLY_WORKER_APP=sigma-worker-proud-tree-92
export PATH="$HOME/.fly/bin:$PATH"

# Generate once; save INTERNAL_SECRET somewhere safe — worker must match API.
export INTERNAL_SECRET="$(openssl rand -hex 32)"
echo "INTERNAL_SECRET=$INTERNAL_SECRET   # save this"

# --- Shared on BOTH apps (same values) ----------------------------------------
fly secrets set -a "$FLY_API_APP" \
  INTERNAL_SECRET="$INTERNAL_SECRET" \
  DATABASE_URL='postgresql+asyncpg://USER:PASS@HOST.tsdb.cloud:5432/tsdb?sslmode=require' \
  REDIS_URL='rediss://default:TOKEN@HOST.upstash.io:6379' \
  SENTRY_DSN='https://KEY@oORG.ingest.sentry.io/PROJECT'

fly secrets set -a "$FLY_WORKER_APP" \
  INTERNAL_SECRET="$INTERNAL_SECRET" \
  DATABASE_URL='postgresql+asyncpg://USER:PASS@HOST.tsdb.cloud:5432/tsdb?sslmode=require' \
  REDIS_URL='rediss://default:TOKEN@HOST.upstash.io:6379' \
  SENTRY_DSN='https://KEY@oORG.ingest.sentry.io/PROJECT'

# --- Equity broker + data (both apps — API serves /signals, worker trades) ----
fly secrets set -a "$FLY_API_APP" \
  ALPACA_API_KEY='YOUR_ALPACA_KEY' \
  ALPACA_SECRET='YOUR_ALPACA_SECRET' \
  TIINGO_API_KEY='YOUR_TIINGO_TOKEN'

fly secrets set -a "$FLY_WORKER_APP" \
  ALPACA_API_KEY='YOUR_ALPACA_KEY' \
  ALPACA_SECRET='YOUR_ALPACA_SECRET' \
  TIINGO_API_KEY='YOUR_TIINGO_TOKEN'

# Optional: FinBERT on worker (or set SENTIMENT_PROVIDER=none in fly.toml [env])
# fly secrets set -a "$FLY_WORKER_APP" HUGGINGFACE_TOKEN='hf_...'

# Verify (names only — no values printed)
fly secrets list -a "$FLY_API_APP"
fly secrets list -a "$FLY_WORKER_APP"
```

**Clerk / Stripe:** add when Vercel web is deployed (`CLERK_SECRET_KEY`, `STRIPE_SECRET_KEY`, … on API only).

---

## 6. Migrations 001–012 (prod)

Requires §5 secrets (`DATABASE_URL` on API). From repo root:

```bash
export FLY_API_APP=sigma-api-proud-tree-92
DB=$(fly ssh console -a "$FLY_API_APP" -C 'env | grep ^DATABASE_URL=' | cut -d= -f2-)
for f in packages/db/migrations/*.sql; do
  echo "Applying $f"
  psql "$(echo "$DB" | sed 's/postgresql+asyncpg:/postgresql:/')" \
    -v ON_ERROR_STOP=1 -f "$f"
done
```

Alternative: run `psql` from your laptop with the Timescale URL directly (same SQL files).

---

## 7. Deploy

```bash
export FLY_WORKER_APP=sigma-worker-proud-tree-92
cd apps/api && fly deploy && cd ../..

fly deploy -a "$FLY_WORKER_APP" \
  --config apps/worker/fly.toml \
  --dockerfile apps/worker/Dockerfile .
```

Worker build context is the **repo root** (Dockerfile COPYs `apps/api` including whitelisted `ensemble_v1.0.pkl`).

---

## 8. Verify

```bash
export FLY_API_APP=sigma-api-proud-tree-92
export FLY_WORKER_APP=sigma-worker-proud-tree-92
curl "https://${FLY_API_APP}.fly.dev/health"
curl "https://${FLY_API_APP}.fly.dev/health/worker"
```

During US market hours (09:30–16:00 ET, weekdays):

```bash
fly logs -a "$FLY_WORKER_APP"
# Expect: singleton lock acquired
#         [equity] sizing equity = <Alpaca paper balance>
#         [equity-data] tiingo served AAPL ...
#         no "model registry unavailable" / heuristic-only warnings
```

Postgres check:

```sql
SELECT count(*) FROM orders WHERE asset_class = 'equity';
-- Should grow during RTH; confirm in Alpaca paper dashboard too.
```

---

## 9. Done when

- [ ] Both apps deployed and `/health` returns `ok`
- [ ] `/health/worker` returns `ok` during RTH (may be `unknown` off-hours — expected)
- [ ] At least one successful equity tick logged; no recurring Sentry noise
- [ ] Operator begins **2+ week paper observation** (M1 success criterion)
- [ ] Add Sprint 1 retro paragraph under `docs/ROADMAP.md` Sprint 1 header

---

## Parallel tracks

| Track | Status | Doc |
|-------|--------|-----|
| M1 mega-cap paper (live `EQUITY_UNIVERSE`) | In progress — DGX worker | This checklist, [`ROADMAP.md`](ROADMAP.md) |
| Emerging Tech 16 reporting | Not blocking M1 — compare CLI / future preset | [`universes/EMERGING_TECH_WORK_PLAN.md`](universes/EMERGING_TECH_WORK_PLAN.md) |

---

## Blockers log

| Blocker | Resolution |
|---------|------------|
| `flyctl` / `fly` not installed | **Resolved** — `~/.fly/bin/flyctl` v0.4.57 (arm64) |
| Fly auth | **Resolved** — `jonaston015@gmail.com` |
| Global `sigma-api` name taken | **Resolved** — owned apps `sigma-api-proud-tree-92` + `sigma-worker-proud-tree-92`; committed in `2497aba` |
| Fly apps have zero secrets | **Partial** — `DATABASE_URL` staged on both apps (real Tiger creds); still need `REDIS_URL`, `INTERNAL_SECRET`, Alpaca, Tiingo, Sentry (§5) |
| No prod `DATABASE_URL` locally | **Resolved** — Tiger CLI (`tiger db connection-string e25vkdi72j`); password in keyring via `tiger db save-password` |
| Prod migrations 001–012 | **Resolved** (2026-06-02) — applied to Tiger service `e25vkdi72j`; `timescaledb` + `vector` enabled |
| Fly deploy | **Deferred** — DGX-first for 24/7 algo iteration; time-box Fly for M1 soak when ready (fix `.dockerignore` before deploy — prior build sent ~5GB context) |
| `tiger mcp install` | Run interactively in terminal (needs TTY for client picker) |
| Docker port 5433 conflict (local only) | Use `POSTGRES_HOST_PORT=5434 docker compose up -d` |
