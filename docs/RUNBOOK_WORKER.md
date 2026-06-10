# SIGMA — Worker operations runbook

What to do when the worker is placing orders you did not expect, when you need to stop trading safely, or when liveness looks wrong. Pair with [`DEPLOY.md`](../DEPLOY.md), [`docs/DEPLOY_EQUITY.md`](./DEPLOY_EQUITY.md), and [`05_API_REFERENCE.md`](../05_API_REFERENCE.md) (execution + `/health/worker`).

**Assumption:** one Fly app `sigma-worker` (or local process) holds the **Redis singleton lock**. Never scale to two machines for the same asset-class set without splitting `WORKER_ASSET_CLASSES` and Postgres books.

---

## Symptoms → first actions

| Symptom | First action |
|---------|----------------|
| Orders still appearing for one venue | `POST /execution/pause` for that `asset_class` (fastest, no redeploy) |
| All venues must stop immediately | Pause each class **or** `fly scale count 0 -a sigma-worker` |
| Worker logs errors every tick | Check Sentry; pause affected class; inspect `fly logs -a sigma-worker` |
| `/health/worker` shows `stale: true` | Worker down or stuck; see [Restart safely](#restart-safely) |
| `/health/worker` shows `paused: true` | Expected after pause — not an incident |
| Second worker exited on startup | Correct — singleton lock held elsewhere; do not force two instances |
| Duplicate orders suspected | Query `orders` by `client_order_id`; pause class; do not delete rows |

---

## Stop one asset class (preferred)

Halts **new** ticks for that class; open positions remain; exit logic does not run while paused.

```bash
API=https://sigma-api.fly.dev   # or http://localhost:8000
SECRET=<INTERNAL_SECRET>

curl -s -X POST "$API/execution/pause" \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-Internal-Secret: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"asset_class":"equity","reason":"operator halt"}'
```

Verify:

```bash
curl -s "$API/execution/status" -H "Authorization: Bearer $API_KEY"
curl -s "$API/health/worker"
```

Resume when ready:

```bash
curl -s -X POST "$API/execution/resume" \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-Internal-Secret: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"asset_class":"equity"}'
```

Implementation: Redis pause flag read each loop iteration in `apps/worker/main.py`; heartbeats stay fresh with `status: paused`.

---

## Stop the whole worker (Fly)

```bash
fly scale count 0 -a sigma-worker
```

- SIGTERM is sent (`kill_signal` in `apps/worker/fly.toml`).
- In-flight tick: the loop checks `stop` between asset-class iterations; there is **no** mid-symbol guarantee yet (Sprint 3 backlog: graceful shutdown test).
- Singleton lock TTL expires after ~3× max tick interval; another instance may acquire lock after scale-up.

**Do not** run two `sigma-worker` machines with overlapping `WORKER_ASSET_CLASSES` — they will race on `positions` / `orders`.

---

## Stop live money (beyond pause)

Pause stops **new** worker-driven orders. Live executors also require explicit flags and approval:

1. `POST /execution/revoke_live` (internal secret) — clears session live approval.
2. Set executor env to paper / sandbox (`EXECUTOR_MODE`, `COINBASE_SANDBOX`, Alpaca paper keys) via `fly secrets` and redeploy if needed.
3. See [`docs/GO_LIVE.md`](./GO_LIVE.md) for the full gate checklist.

---

## Restart safely

1. Pause all active asset classes (or scale to 0).
2. Confirm no unexpected open orders at broker (Alpaca paper dashboard, Coinbase, etc.).
3. Optional: inspect Postgres:

```sql
SELECT asset_class, symbol, qty, closed FROM positions WHERE closed = FALSE;
SELECT asset_class, symbol, side, ts, executor FROM orders ORDER BY ts DESC LIMIT 20;
```

4. Scale worker back up:

```bash
fly scale count 1 -a sigma-worker
fly logs -a sigma-worker
```

5. `curl …/health/worker` — each class should show `healthy: true` within 2× tick cadence.

---

## Manual single tick (debug)

**Internal-only** — runs full `tick_once` in-process on the API VM (heavy import path):

```bash
curl -s -X POST "$API/execution/run_cycle" \
  -H "X-Internal-Secret: $SECRET" \
  -H "Content-Type: application/json" \
  -d '{"asset_class":"equity"}'
```

Use sparingly in prod; prefer logs + pause for incidents.

---

## Options worker (separate process)

Options run beside Moomoo OpenD (local/VPS), not on Fly. Same Postgres/Redis; separate heartbeat key `option`. If options misbehave:

- Stop that process (systemd/docker) — does not stop equity/crypto on Fly.
- OpenD reachability appears under `opend` on `/health/worker` when probed.

See [`docs/DEPLOY_OPTIONS.md`](./DEPLOY_OPTIONS.md).

---

## Background jobs (scheduler)

On the singleton holder only (`WORKER_SCHEDULER_ENABLED`, default on):

| Job | Risk if run twice |
|-----|-------------------|
| `label_and_evaluate_job` | Duplicate evaluation rows (low) |
| `train_and_propose_job` | Duplicate pending promotions (human must reject extras) |
| `embed_signals` (if enabled) | Duplicate embeddings (idempotent upsert depends on script) |

If scheduler errors flood logs but trading is fine: set `WORKER_SCHEDULER_ENABLED=false` and redeploy — trading loop continues.

---

## Escalation checklist

1. Pause affected `asset_class`(es).
2. Capture `fly logs -a sigma-worker` (last 30 min) + Sentry issue link.
3. Snapshot `orders` / `positions` / latest `audit_records` for the symbol.
4. Scale to 0 if pause is insufficient.
5. File retro note under the active sprint in [`docs/ROADMAP.md`](./ROADMAP.md).

**Not in scope here:** broker-side cancel-all (implement per executor when M3 live trading hardens); position reconcile on startup (Sprint 2 backlog).
