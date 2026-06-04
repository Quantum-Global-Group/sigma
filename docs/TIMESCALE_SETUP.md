# SIGMA — Timescale / Postgres setup

Sigma needs **PostgreSQL with the TimescaleDB extension** for production (Fly deploy).
This is **not** an REST API key like Alpaca or Tiingo — you get a **`DATABASE_URL`**
(connection string with host, user, password, database).

The [timescale/timescaledb](https://github.com/timescale/timescaledb) GitHub repo is the
**open-source extension** source code. You do not sign up there for credentials.

---

## What Sigma uses it for

| Migration | Needs |
|-----------|--------|
| `002_timescaledb.sql` | `CREATE EXTENSION timescaledb` + hypertables on `candles`, `signal_history`, etc. |
| `012_pgvector_embeddings.sql` | `CREATE EXTENSION vector` (optional for M1 deploy; required for embed job) |

Vanilla Postgres (no Timescale) will fail on migration `002` unless you edit it (see `DEPLOY.md` option C).

---

## Option A — Timescale Cloud / Tiger Cloud (recommended for Fly)

**Use this for Sprint 1** so `sigma-api-proud-tree-92` and `sigma-worker-proud-tree-92` on Fly.io can reach the database.

1. Sign up: [console.cloud.timescale.com](https://console.cloud.timescale.com)  
   (Timescale’s managed product is also marketed as **Tiger Cloud** — same idea: hosted Postgres + Timescale.)

2. **Create a service** (free trial available):
   - Region: pick one close to Fly `ord` (e.g. US East) if possible
   - Postgres 15+ recommended

3. **Enable extensions** (dashboard → service → Extensions, or run in SQL editor after connect):
   ```sql
   CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
   CREATE EXTENSION IF NOT EXISTS vector;   -- for migration 012 (embeddings)
   ```
   If `vector` is not available on your plan, M1 paper trading still works; skip migration `012` or run embed job later on DGX local DB.

4. **Copy the connection string** from the dashboard:
   - Look for **“Connection string”** or **“Service URL”**
   - User is often `tsdbadmin`
   - Must include **`?sslmode=require`** for cloud

5. **Convert to Sigma’s async URL** (FastAPI / SQLAlchemy):

   ```
   postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
   ```

   Example shape (yours will differ):

   ```
   postgresql+asyncpg://tsdbadmin:YOUR_PASSWORD@abc123.us-east-1.tsdb.cloud.timescale.com:5432/tsdb?sslmode=require
   ```

6. **Set on Fly** (both apps, same URL):

   ```bash
   export FLY_API_APP=sigma-api-proud-tree-92
   export FLY_WORKER_APP=sigma-worker-proud-tree-92

   fly secrets set -a "$FLY_API_APP" \
     DATABASE_URL='postgresql+asyncpg://tsdbadmin:PASSWORD@HOST:5432/tsdb?sslmode=require'

   fly secrets set -a "$FLY_WORKER_APP" \
     DATABASE_URL='postgresql+asyncpg://tsdbadmin:PASSWORD@HOST:5432/tsdb?sslmode=require'
   ```

7. **Apply migrations** — see [`SPRINT1_DEPLOY_CHECKLIST.md`](SPRINT1_DEPLOY_CHECKLIST.md) §6.

There is **no separate “Timescale API key”** env var in Sigma — only `DATABASE_URL`.

---

## Option B — Local Docker (DGX dev / `make e2e` only)

**Not reachable from Fly.** Use for local development and tests.

```bash
# Repo default (docker compose)
docker compose up -d postgres redis
make migrate
```

Or Timescale’s one-liner (different port **6543**):

```bash
curl -sL https://tsdb.co/start-local | sh
psql -h localhost -p 6543 -U postgres   # password: password
```

Local `DATABASE_URL`:

```
postgresql+asyncpg://postgres:password@localhost:5432/sigma
```

(pgvector: migration `012` applies if the `timescale/timescaledb` image includes it or you use the repo’s `docker-compose.yml` Postgres image.)

---

## Option C — Self-hosted Timescale on Fly (advanced)

See [`DEPLOY.md`](../DEPLOY.md) §4 option B — run `timescale/timescaledb` as its own Fly machine. More ops; no separate vendor signup beyond Fly.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `extension "timescaledb" is not available` | Use Timescale-capable host (Cloud or `timescale/timescaledb` image), not plain RDS/Fly Postgres |
| `extension "vector" is not available` | Enable on Cloud or skip `012` for M1; run embeddings on local DGX DB |
| Fly worker can’t connect | URL must be **public** cloud host + `sslmode=require`; localhost won’t work |
| Password special characters | URL-encode `@`, `#`, `/`, etc. in the password segment |

---

## After `DATABASE_URL` is set

Continue Sprint 1: [`SPRINT1_DEPLOY_CHECKLIST.md`](SPRINT1_DEPLOY_CHECKLIST.md) §5 (remaining secrets) → §6 migrations → §7 deploy.
