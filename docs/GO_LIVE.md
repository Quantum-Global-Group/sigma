# SIGMA — Go-Live Runbook (paper → real money)

> **This is a human-owned, deliberate procedure.** The codebase never enables live
> trading, funds an account, or places a real-money order on its own. Every step
> below that moves real money is performed by you. The software only provides
> guardrails so that when you choose to go live, it is safe and reversible.

Going live is gated by **three independent locks** — all must be set, by you:

1. **Per-venue allow-live flags** (config): e.g. `ALPACA_ALLOW_LIVE=true` **and**
   `ALPACA_PAPER=false` (same shape for `OANDA_*`, `MOOMOO_*`). A live executor
   refuses to even construct otherwise.
2. **Session approval gate** (runtime): `POST /execution/approve_live`. Even with the
   flags on, no real-money order places until this is approved — and it expires
   daily and is revocable. Paper orders are never gated.
3. **Funded broker account**: you fund and verify the broker yourself.

## 0. Prerequisites
- A green paper track record (orders, P&L, the self-evolution loop running).
- Order caps configured (`PER_TRADE_NOTIONAL_CAP_USD`, `ALPACA_MAX_ORDER_NOTIONAL`,
  `OPTION_MAX_CONTRACTS`, net-Greek caps).
- Monitoring reachable: `/health/worker`, `/portfolio/pnl`, the dashboards.

## 1. Preflight
```bash
curl -s https://sigma-api.fly.dev/execution/preflight -H "X-Internal-Secret: $S" | jq
```
Confirm `ready: true` and review every check (order caps, kill switch, model,
venue modes). Do not proceed on a failed critical check.

## 2. Flip ONE venue to live (smallest first)
Set the venue's secrets + flags (commit fly.toml env / `fly secrets set`), e.g. equity:
```
ALPACA_PAPER=false
ALPACA_ALLOW_LIVE=true
ALPACA_MAX_ORDER_NOTIONAL=200      # start tiny
PER_TRADE_NOTIONAL_CAP_USD=200
```
Redeploy. The executor now *can* trade live — but the approval gate still blocks it.

## 3. Approve the session (the go-ahead)
```bash
curl -XPOST https://sigma-api.fly.dev/execution/approve_live -H "X-Internal-Secret: $S" \
     -H 'content-type: application/json' -d '{"reason":"equity live, $200 cap, staged rollout"}'
```
Approval lasts 24h. The first real-money order can now place — at your tiny cap.

## 4. Watch the first live fills
- `/health/worker` healthy; `/portfolio/pnl` updating; orders appearing at the broker.
- Keep the size tiny for a full session before scaling caps.

## 5. Scale gradually
Raise the caps step by step across sessions, re-running preflight each time. Add
venues (forex, options) one at a time, each with its own flags + a fresh approval.

## Rollback / kill (any time)
- **Pause a venue:** `POST /execution/pause {"asset_class":"equity"}` — stops new
  ticks immediately, no redeploy.
- **Revoke live:** `POST /execution/revoke_live` — back to paper-only behavior for
  every venue (the gate blocks live orders again).
- **Flip flags back:** `ALPACA_PAPER=true` / `ALPACA_ALLOW_LIVE=false` + redeploy.
- **Kill switch:** trips halt new entries in the worker (exits still flow).

## What the software will NOT do for you
Enable a venue, set `*_allow_live`, fund an account, approve a session, or place a
real order without your explicit action above. By design.
