# SIGMA — Forex Deploy (OANDA practice)

The forex overlay on the general [`DEPLOY.md`](../DEPLOY.md): trade **currency pairs
on OANDA** from the same Fly `sigma-worker`. Forex uses OANDA's v20 **cloud REST API**,
so — unlike options (see [`DEPLOY_OPTIONS.md`](DEPLOY_OPTIONS.md)) — it runs on Fly
unchanged, alongside crypto/equity.

> This doc only changes the worker's asset class, executor, and OANDA secrets. Read
> `DEPLOY.md` for the full infra picture (Postgres, Redis, API, web).

## 0. Prerequisites

- **OANDA practice account** — API token + account ID
  (https://www.oanda.com/demo-account/ → *Manage API Access* for the token; the
  account ID looks like `101-001-1234567-001`).
- The shared `sigma-api` + `sigma-worker` Fly apps + Postgres + Redis already
  provisioned per `DEPLOY.md`.

## 1. Point the worker at forex

Edit `apps/worker/fly.toml` `[env]` (commit the change) — add `forex` to the list:

```toml
  WORKER_ASSET_CLASSES = "crypto,forex"   # or "crypto,equity,forex"
  FOREX_EXECUTOR = "oanda"                # paper still — OANDA_PAPER guards live
  WORKER_TICK_SECONDS_FOREX = "900"       # H4 bars → 15-min cadence is plenty
  # already set: OANDA_ENVIRONMENT="practice", OANDA_PAPER="true",
  #              OANDA_ALLOW_LIVE="false"
  # Optional: FOREX_UNIVERSE = "EUR_USD,GBP_USD,AUD_USD,USD_JPY,USD_CAD"
```

The default universe is USD-quote majors so paper P&L is exact (a USD-quote pair's
P&L is already in USD; USD-base/cross pairs are in the quote currency — a known
paper-MVP simplification).

## 2. Set the OANDA secrets

```bash
fly secrets set -a sigma-worker \
  OANDA_API_TOKEN=<your practice token> \
  OANDA_ACCOUNT_ID=101-001-1234567-001
```

## 3. Deploy + verify

```bash
fly deploy                      # from repo root (build context = repo root)
# Worker logs should show: "[forex] tick: N symbols" on the cadence.
curl -s https://sigma-api.fly.dev/health/worker | jq '.workers.forex'
# → {"status":"ok","healthy":true,...}
```

In the web app, the **Forex** page lists open FX positions + fills, and **P&L**
shows the forex breakdown. Orders/positions also filter by `forex`.

## 4. Going live (out of scope for the alpha)

Live forex requires `OANDA_ALLOW_LIVE=true` **and** `OANDA_PAPER=false` **and**
`OANDA_ENVIRONMENT=live` — a deliberate three-way guardrail. Keep it paper until the
strategy is proven.

## Pause / resume

Halt forex without redeploying (e.g. during a news event) — internal-secret gated:

```bash
curl -XPOST https://sigma-api.fly.dev/execution/pause  -H "X-Internal-Secret: $S" \
     -H 'content-type: application/json' -d '{"asset_class":"forex","reason":"NFP"}'
curl -XPOST https://sigma-api.fly.dev/execution/resume -H "X-Internal-Secret: $S" \
     -H 'content-type: application/json' -d '{"asset_class":"forex"}'
```
