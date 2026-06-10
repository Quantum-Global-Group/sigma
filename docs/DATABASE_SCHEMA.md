# SIGMA — Database schema supplement (005–012)

Companion to [`04_DATABASE_SCHEMA.md`](../04_DATABASE_SCHEMA.md), which documents migrations **001–004**. This file summarizes **005–012** so operators and agents can grep one place for the trading/ML schema without re-reading every SQL file.

**Apply order:** `packages/db/migrations/001_initial_schema.sql` … `012_pgvector_embeddings.sql` (forward-only; see ROADMAP backlog for rollback notes on 005/006).

---

## Migration 005 — Trading + asset class

**File:** `005_trading_and_asset_class.sql`

| Change | Purpose |
|--------|---------|
| `asset_class` on `signal_history`, `signal_cache`, `users.default_asset_class` | Multi-venue signals; cache PK widened to `(asset_class, ticker, timeframe)` |
| `component_weights` JSONB on `signal_history` | Combiner breakdown for strategy reporting |
| `usage_logs.internal` + system user `00000000-0000-0000-0000-000000000001` | Worker `/signals` traffic excluded from billing |
| **`candles`** hypertable | OHLCV per `(asset_class, symbol, timeframe, ts)` |
| **`positions`** | House-book open/closed positions |
| **`orders`** | Fill log (`executor`, `external_id`, `status`, `raw`) |
| **`exit_state`** | Trailing stop / partial-TP per position |

---

## Migration 006 — asset_class NOT NULL

**File:** `006_asset_class_not_null.sql`

Fails fast if any `signal_history` row still has `NULL asset_class`. Run only after 005 backfill is verified in prod.

---

## Migration 007 — Order idempotency

**File:** `007_order_idempotency.sql`

| Column | Purpose |
|--------|---------|
| `client_order_id` | Unique partial index — retries must not double-place |
| `order_type`, `time_in_force`, `limit_px`, `stop_px` | Richer `OrderIntent` persistence |

---

## Migration 008 — Options columns + quotes

**File:** `008_options.sql`

Extends **`orders`** and **`positions`** with option contract fields (`underlying`, `expiry`, `strike`, `"right"`, `multiplier`, `meta`). Adds **`option_quotes`** hypertable for chain snapshots (Moomoo/OpenD path).

---

## Migration 009 — Decision logging (audit)

**File:** `009_decision_logging.sql`

| Change | Purpose |
|--------|---------|
| `signal_history.realized_return`, `outcome`, `labeled_at` | Outcome labeling job (`ml/labeling.py`) |
| **`audit_records`** hypertable | Full per-tick provenance (`data`, `features`, `signal`, `risk`, `gates`, `order_info`) — equity/crypto/forex/options |

Worker persists the same `AuditLog` shape as options for all asset classes (2026-06 audit parity).

---

## Migration 010 — Model evolution

**File:** `010_model_evolution.sql`

| Table | Purpose |
|-------|---------|
| **`model_evaluations`** | Measured performance per `(asset_class, model_type, model_version)` |
| **`model_promotions`** | Proposed champion changes (`pending` → human approve/reject) |
| **`model_champions`** | Active version per `(asset_class, model_type)` — worker resolves each tick |

API: `GET/POST /models/*` — see [`05_API_REFERENCE.md`](../05_API_REFERENCE.md).

---

## Migration 011 — PnL snapshots

**File:** `011_pnl.sql`

| Table | Purpose |
|-------|---------|
| **`equity_snapshots`** hypertable | Periodic account value + realized/unrealized PnL; `by_asset_class` JSONB for dashboard charts |

Written by worker scheduler `equity_snapshot_job` (and on demand).

---

## Migration 012 — pgvector embeddings (MVP)

**File:** `012_pgvector_embeddings.sql`

Requires Postgres **`vector`** extension (Timescale Cloud / self-hosted with pgvector).

| Table | Purpose |
|-------|---------|
| **`signal_embeddings`** hypertable | 64-dim `embedding` + `features`, `component_signals`, `outcome` for similarity search |

Offline job: `apps/api/scripts/embed_signals.py`. Scheduler flag: `EMBED_SIGNALS_ENABLED` (see [`03_ENV_VARS.md`](../03_ENV_VARS.md)).

After bulk load, run `ANALYZE signal_embeddings` so the IVFFlat cosine index is effective.

---

## Quick reference — tables introduced 005–012

```
candles, positions, orders, exit_state
option_quotes
audit_records
model_evaluations, model_promotions, model_champions
equity_snapshots
signal_embeddings
```

Plus column additions on existing tables (`signal_history`, `signal_cache`, `usage_logs`, `users`, `orders`, `positions`).
