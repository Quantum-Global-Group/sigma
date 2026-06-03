# SIGMA — End-to-End Validation

How to prove the platform actually works against real infrastructure — not just
mocked unit tests. Three layers, increasing in what they touch:

| Layer | Proves | Needs |
|---|---|---|
| **A. Offline smoke** | the full loop persists real rows to real Postgres | Docker only — **automated** |
| **B. OANDA practice** | live forex market data + a paper account | your OANDA practice token |
| **C. Deploy** | 24/7 operation | Fly + (for options) a local/VPS OpenD |

> **Why this exists:** every unit test mocks the database (`tests/conftest.py` yields a
> `_fake_db`). Layer A caught a real bug mocks missed — migration `008_options.sql` used the
> reserved keyword `right` as an unquoted column, so on a real Postgres the whole migration
> aborted and the option columns never existed. Run real DB validation.

---

## A. Offline smoke (automated — no creds, no network)

Brings up TimescaleDB + Redis, applies migrations `001–012`, seeds the system/dev user, and runs
the full loop with a **synthetic market adapter** + the **paper executor**, asserting real rows
land in every table:

```bash
make e2e
```

What it checks (`apps/api/scripts/e2e_smoke.py`):
- **Phase 1** — `tick_once("equity")` → `signal_history` + `orders` + `positions` rows.
- **Phase 2** — seed backdated signals + candles → `label_outcomes` → `evaluate_model` →
  a `model_evaluations` row (labeling needs *elapsed* forward bars, so it seeds history).
- **Phase 3** — `aggregate_pnl` + `snapshot_equity` → an `equity_snapshots` row.

Expected tail: `=== 8/8 checks passed ===`. Spot-check the rows:

```bash
docker compose exec -T postgres psql -U postgres -d sigma -c \
  "select 'signals' t, count(*) from signal_history
   union all select 'orders', count(*) from orders
   union all select 'positions', count(*) from positions
   union all select 'evaluations', count(*) from model_evaluations
   union all select 'equity_snaps', count(*) from equity_snapshots;"
```

**As a durable test** (CI-optional — skipped unless a real DB is pointed at):

```bash
E2E_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sigma \
  pytest apps/api/tests/test_e2e_integration.py -v
```

`make e2e-down` stops the containers (data persists in the volume; `make clean` wipes it).

---

## Audit & strategy reports (equity-first)

After an equity, crypto, or forex tick (`tick_once(...)` or the worker loop), every
symbol evaluation is persisted to `audit_records` with gate outcomes (G1_data → G8_fill)
and a final decision (`placed`, `skipped`, or `rejected`). Options use the same table
via `options_tick.py`. Query recent equity audit rows:

```bash
docker compose exec -T postgres psql -U postgres -d sigma -c \
  "SELECT ts, symbol, decision, gates->-1 AS last_gate, signal->>'direction' AS direction
   FROM audit_records
   WHERE asset_class = 'equity'
   ORDER BY ts DESC
   LIMIT 20;"
```

Filter skipped symbols to see *why* a trade was not taken (failed gate + reasons in
`gates` JSONB):

```bash
docker compose exec -T postgres psql -U postgres -d sigma -c \
  "SELECT symbol, decision, gates
   FROM audit_records
   WHERE asset_class = 'equity' AND decision = 'skipped'
   ORDER BY ts DESC LIMIT 10;"
```

**Weekly strategy report API** (requires API key from `make seed`):

```bash
curl -s "http://localhost:8001/strategies/performance/report?asset_class=equity&period=7d" \
  -H "Authorization: Bearer <api-key>" | jq '.summary, .strategies'
```

Rolling window variants: `period=7d`, `14d`, `24h`. The dashboard at `/strategies`
defaults to equity + 7d and renders the markdown `summary` field.

**Signal embeddings job** (pgvector, migration 012):

```bash
make migrate
cd apps/api && PYTHONPATH=. python scripts/embed_signals.py --asset-class equity
# or enable nightly: EMBED_SIGNALS_ENABLED=true on the worker
```

See also [`docs/MODELS.md`](MODELS.md) § Signal embeddings.

---

## B. OANDA practice validation (you run — needs your token)

Forex uses OANDA's cloud REST API, so this is the easiest *live-paper* proof (no OpenD needed).

```bash
cd apps/api
pip install oandapyV20                     # in requirements.txt; may not be in the venv yet
export OANDA_API_TOKEN=...                  # OANDA practice token
export OANDA_ACCOUNT_ID=101-001-1234567-001
export OANDA_ENVIRONMENT=practice
export OANDA_PAPER=true

# 1. Connectivity: account NAV + EUR_USD candles (no orders placed)
PYTHONPATH=. python scripts/check_oanda.py
```

Then a real paper forex tick through the API:

```bash
# 2. Start the API (Postgres+Redis already up from `make e2e`)
cd apps/api
export DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sigma
export REDIS_URL=redis://localhost:6379
export INTERNAL_SECRET=dev-internal-secret
export FOREX_EXECUTOR=oanda
uvicorn main:app --reload --port 8000

# 3. Trigger one forex tick (internal-secret gated)
curl -XPOST http://localhost:8000/execution/run_cycle \
  -H "X-Internal-Secret: dev-internal-secret" -H 'content-type: application/json' \
  -d '{"asset_class":"forex"}'

# 4. Inspect what it did
curl -s http://localhost:8000/positions?asset_class=forex -H "Authorization: Bearer <api-key>" | jq
curl -s http://localhost:8000/portfolio/pnl              -H "Authorization: Bearer <api-key>" | jq
```

(Get `<api-key>` from `make seed` output.) Orders should appear in your OANDA practice account.

---

## C. Deployment (you run — needs accounts)

- **Forex on Fly:** [`DEPLOY_FOREX.md`](DEPLOY_FOREX.md) — set the OANDA secrets, add `forex` to
  `WORKER_ASSET_CLASSES`, deploy. Verify via `/health/worker`.
- **Options on local/VPS:** [`DEPLOY_OPTIONS.md`](DEPLOY_OPTIONS.md) — OpenD can't run on Fly; run a
  dedicated options worker next to it against the same Postgres/Redis.
- **Going live:** [`GO_LIVE.md`](GO_LIVE.md) — the staged, human-owned paper→real procedure.
