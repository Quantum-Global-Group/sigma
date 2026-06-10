# SIGMA — Options Deploy (Moomoo paper, local/VPS)

The options overlay on [`DEPLOY.md`](../DEPLOY.md). **Options cannot run on Fly.**
Moomoo's SDK talks to a local **OpenD** gateway daemon on `127.0.0.1:11111`, not a
cloud REST API — so a Fly machine can't reach it. Instead, run a **dedicated options
worker on a local box or VPS** where OpenD is running, pointed at the **same**
Postgres + Redis as the Fly stack. Crypto/equity/forex keep running on Fly
([`DEPLOY_FOREX.md`](DEPLOY_FOREX.md)); options join the same shared book.

```
  Fly: sigma-worker  ──┐
   (crypto/equity/forex)│            ┌─ Timescale Cloud (Postgres)
                        ├─ shared ──►│
  Local/VPS: options    │            └─ Upstash (Redis)
   worker + OpenD     ──┘
```

## 0. Prerequisites (on the local box / VPS)

- **Moomoo/Futu account** with a **paper** trading account enabled.
- **OpenD** gateway installed + running (download from Moomoo; run it logged in so
  it listens on `127.0.0.1:11111`).
- Python 3.12 + the repo checked out; `pip install -r apps/api/requirements.txt`
  (includes `moomoo-api`).
- The **same** `DATABASE_URL` + `REDIS_URL` the Fly apps use (so positions/orders
  land in one shared book and `/health/worker` sees the options heartbeat).

## 1. Start OpenD

Launch OpenD and log into the paper account. Confirm it's listening:

```bash
curl -s 127.0.0.1:11111 >/dev/null && echo "OpenD up" || echo "OpenD not reachable"
```

## 2. Configure + run the options worker

```bash
cd sigma
export WORKER_ASSET_CLASSES=option
export OPTION_EXECUTOR=moomoo
export MOOMOO_HOST=127.0.0.1
export MOOMOO_PORT=11111
export MOOMOO_PAPER=true
export MOOMOO_ALLOW_LIVE=false
export DATABASE_URL=<same as Fly>          # Timescale Cloud
export REDIS_URL=<same as Fly>             # Upstash
export MODEL_DIR=apps/api/ml/saved_models
export INTERNAL_SECRET=<same as Fly>
export WORKER_SCHEDULER_ENABLED=false      # let the Fly worker own the cron jobs
# Optional: export OPTION_UNIVERSE="AAPL,MSFT,NVDA,SPY,QQQ"

PYTHONPATH=apps/api python -m worker.main
```

The worker logs `[option] tick: N underlyings`, runs the 5 validation gates, places
paper orders via OpenD, and marks/settles/exits open option positions each tick.

> **Singleton note:** the worker singleton lock is global. Run the **options** worker
> with `WORKER_ASSET_CLASSES=option` only, and the **Fly** worker with the other
> classes — they coordinate through the shared Redis lock + per-class heartbeats, so
> they don't double-place. Don't run two workers covering the *same* asset class.

## 3. Keep it running 24/7

**systemd** (`/etc/systemd/system/sigma-options.service`):

```ini
[Unit]
Description=SIGMA options worker
After=network-online.target

[Service]
WorkingDirectory=/opt/sigma
EnvironmentFile=/opt/sigma/.env.options
Environment=PYTHONPATH=apps/api
ExecStart=/usr/bin/python3 -m worker.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now sigma-options
journalctl -u sigma-options -f
```

(OpenD itself must also be kept running + logged in — supervise it separately; it's a
GUI/daemon app, not a systemd-native service.)

## 4. Verify

```bash
curl -s https://sigma-api.fly.dev/health/worker | jq '.workers.option'
# → {"status":"ok","healthy":true,...}
psql "$DATABASE_URL" -c \
  "select count(*) from orders where asset_class='option';"
```

The web **Options** page shows candidates + positions + Greeks; **P&L** includes the
options breakdown.

## 5. Pause / going live

Pause options without stopping the process (internal-secret gated):

```bash
curl -XPOST https://sigma-api.fly.dev/execution/pause -H "X-Internal-Secret: $S" \
     -H 'content-type: application/json' -d '{"asset_class":"option"}'
```

Live options require `MOOMOO_ALLOW_LIVE=true` **and** `MOOMOO_PAPER=false` plus the
kill-switch + human-approval gates — out of scope for the alpha.
