# SIGMA — Equity Alpha Deploy (Alpaca paper)

The equity-flavored runbook: deploy `sigma-api` + `sigma-worker` to Fly trading
**US equities on Alpaca paper**, with the trained ensemble and Tiingo data. This
is the equity overlay on the general [`DEPLOY.md`](../DEPLOY.md) — read that for
the full infra picture (Vercel, Stripe, Clerk, webhooks).

> **Crypto vs equity:** the general runbook is crypto-first (Coinbase). This doc
> only changes the worker's asset class, executor, data providers, and secrets.

## 0. Prerequisites

```bash
curl -L https://fly.io/install.sh | sh   # flyctl
fly auth login
# psql for migrations: e.g. apt-get install -y postgresql-client
```

Accounts/keys to have ready:
- **Alpaca paper** — API key + secret (https://app.alpaca.markets/paper/dashboard/overview)
- **Tiingo** — API token (https://www.tiingo.com/account/api/token)
- **Timescale Cloud** — Postgres+TimescaleDB connection string
- **Upstash** — Redis connection string
- (optional) Sentry DSN, HuggingFace token

## 1. Point the worker at equities

Edit `apps/worker/fly.toml` `[env]` (commit the change):

```toml
  WORKER_ASSET_CLASSES = "equity"
  EQUITY_EXECUTOR = "alpaca"
  EQUITY_DATA_PROVIDERS = "tiingo,alpaca,yfinance"
  # already set: ALPACA_PAPER="true", ALPACA_ALLOW_LIVE="false",
  #              MODEL_DIR="/app/api/ml/saved_models"
```

## 2. Provision Fly apps (from repo root)

```bash
cd apps/api    && fly launch --copy-config --no-deploy --org <org> --name sigma-api  && cd ../..
cd apps/worker && fly launch --copy-config --no-deploy --org <org> --name sigma-worker && cd ../..
```

## 3. Postgres (Timescale Cloud) + Redis (Upstash)

Create both in their dashboards; copy the connection strings. Timescale Cloud has
the extension, so `002_timescaledb.sql` applies cleanly.

## 4. Secrets

```bash
# shared on both apps (INTERNAL_SECRET must be identical)
SHARED="INTERNAL_SECRET=$(openssl rand -hex 32) \
  DATABASE_URL=postgresql+asyncpg://tsdbadmin:...@...tsdb.cloud:5432/tsdb?sslmode=require \
  REDIS_URL=rediss://default:...@...upstash.io:6379 \
  SENTRY_DSN=https://...  HUGGINGFACE_TOKEN=hf_..."
fly secrets set -a sigma-api    $SHARED
fly secrets set -a sigma-worker $SHARED

# equity data + execution (worker trades; api needs Tiingo for /signals)
fly secrets set -a sigma-worker ALPACA_API_KEY=... ALPACA_SECRET=... TIINGO_API_KEY=...
fly secrets set -a sigma-api    ALPACA_API_KEY=... ALPACA_SECRET=... TIINGO_API_KEY=...
```

`SENTRY_DSN` on the worker is what turns the loop's `logger.exception` calls into
alerts — set it or you're flying blind.

## 5. Migrations 001–007

```bash
DB=$(fly ssh console -a sigma-api -C 'env | grep ^DATABASE_URL=' | cut -d= -f2-)
for f in packages/db/migrations/*.sql; do
  echo "applying $f"
  psql "$(echo "$DB" | sed 's/postgresql+asyncpg:/postgresql:/')" -v ON_ERROR_STOP=1 -f "$f"
done
```

## 6. Deploy

```bash
cd apps/api && fly deploy && cd ../..
fly deploy -a sigma-worker --config apps/worker/fly.toml --dockerfile apps/worker/Dockerfile .
```

## 7. Verify

```bash
curl https://sigma-api.fly.dev/health          # {"status":"ok"}
curl https://sigma-api.fly.dev/health/worker   # heartbeat-derived liveness
```

`GET /health/worker` returns:
- `unknown` — no heartbeats yet (worker just started, or markets closed all tick)
- `ok` — last tick fresh (< 2x cadence) and successful
- `degraded` — stale heartbeat or last tick errored

During US market hours (09:30–16:00 ET, weekdays), tail the worker:

```bash
fly logs -a sigma-worker
#  expect:  singleton lock acquired
#           [equity] sizing equity = <real Alpaca paper balance>
#           [equity-data] tiingo served AAPL ...
#           one tick per WORKER_TICK_SECONDS_EQUITY (900s); no "model registry unavailable"
```

Then confirm orders flow:

```sql
select count(*) from orders where asset_class='equity';   -- grows during RTH
```

…and that they appear in the Alpaca paper dashboard.

## Notes

- **Markets closed** → the worker logs `market closed — skipping tick` and writes
  no orders. That's expected; `/health/worker` may read `unknown` off-hours.
- **Single instance only.** The worker holds a Redis singleton lock; a second
  instance exits. `apps/worker/fly.toml` also pins one machine. Don't scale it.
- **Going live (real money)** is out of scope for the alpha and gated behind
  `ALPACA_ALLOW_LIVE=true` + `ALPACA_PAPER=false` (M3, with notional caps).
