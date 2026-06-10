# SIGMA — API Reference

> Base URL: `https://api.sigma.dev` (prod) | `http://localhost:8000` (local)
> All endpoints require `Authorization: Bearer YOUR_API_KEY` header unless noted.

---

## Endpoint Map

```mermaid
flowchart LR
  K[Bearer key] --> AUTH{Validate + rate limit}
  AUTH -->|reject| E429[429 / 401]
  AUTH -->|pass| ROUTES
  subgraph ROUTES [Endpoints]
    direction TB
    H[GET /health · /ready]
    S[POST /signals]
    SH[GET /signals/:ticker/history]
    P[POST /portfolio/rebalance]
    B[POST /backtest/run]
    KEYS[GET·POST·DELETE /keys]
    U[GET /usage]
  end
  S --> CACHE{cache hit?}
  CACHE -->|yes| RESP[signal — no charge]
  CACHE -->|no| ML[ML pipeline] --> RESP
```

| Group | Endpoints | Auth |
| --- | --- | --- |
| Health | `GET /health`, `GET /ready` | none |
| Signals | `POST /signals`, `GET /signals/{ticker}/history` | Bearer |
| Portfolio | `POST /portfolio/rebalance` | Bearer |
| Backtest | `POST /backtest/run` | Bearer |
| Keys | `GET/POST/DELETE /keys` | Bearer |
| Usage | `GET /usage` | Bearer |

---

## Authentication

```http
Authorization: Bearer sk_live_xxxxxxxxxxxxxxxxxxxx
```

Keys are prefixed:
- `sk_live_` — production key
- `sk_test_` — test key (no billing, rate limits still apply)

Keys are validated against `api_keys.key_hash` on every request.
Valid keys are cached in Redis for 24 hours to avoid DB hits.

---

## Rate Limits

| Plan | Calls / day | Burst (per minute) |
|------|-------------|-------------------|
| Free | 100 | 10 |
| Pro | 10,000 | 200 |
| Enterprise | Unlimited | 2,000 |

Rate limit headers returned on every response:
```
X-RateLimit-Limit: 10000
X-RateLimit-Remaining: 9847
X-RateLimit-Reset: 1735689600
```

---

## Endpoints

### Health

#### `GET /health`
No auth required. Returns 200 if API is up.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "timestamp": "2026-04-20T14:32:00Z"
}
```

#### `GET /ready`
No auth required. Returns 200 only if DB + Redis are reachable.

---

### Signals

#### `POST /signals`

Generate a trading signal for a ticker.

**Request**
```json
{
  "ticker": "AAPL",
  "timeframe": "daily"
}
```

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `ticker` | string | yes | Any valid symbol e.g. `AAPL`, `BTC-USD` |
| `timeframe` | string | no | `daily` (default) · `4h` · `hourly` |

**Response `200`**
```json
{
  "ticker": "AAPL",
  "timeframe": "daily",
  "signal": "BUY",
  "confidence": 0.7821,
  "predicted_return": 0.0234,
  "model_version": "v1.0",
  "cached": false,
  "timestamp": "2026-04-20T14:32:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `signal` | string | `BUY` · `SELL` · `HOLD` |
| `confidence` | float | 0.0–1.0. Higher = stronger signal |
| `predicted_return` | float | Expected % return (signed). Positive = up |
| `cached` | bool | `true` if served from cache (no billing charge) |

**Errors**
```json
{ "detail": "Invalid ticker: XXXX" }         // 422
{ "detail": "Rate limit exceeded" }           // 429
{ "detail": "Invalid API key" }               // 401
```

---

#### `GET /signals/{ticker}/history`

Return past signals for a ticker.

**Query params**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `timeframe` | string | `daily` | Filter by timeframe |
| `limit` | int | 30 | Max results (1–200) |
| `before` | ISO datetime | now | Cursor for pagination |

**Response `200`**
```json
{
  "ticker": "AAPL",
  "signals": [
    {
      "signal": "BUY",
      "confidence": 0.78,
      "predicted_return": 0.023,
      "timestamp": "2026-04-20T00:00:00Z"
    }
  ],
  "next_cursor": "2026-04-19T00:00:00Z"
}
```

---

### Portfolio

#### `POST /portfolio/rebalance`

Optimize portfolio allocation.

**Request**
```json
{
  "holdings": {
    "AAPL": 10000,
    "MSFT": 8000,
    "GOOGL": 5000
  },
  "method": "mvo",
  "constraints": {
    "max_position": 0.4,
    "min_position": 0.05
  }
}
```

| Field | Type | Values |
|-------|------|--------|
| `holdings` | object | `{ ticker: usd_value }` |
| `method` | string | `mvo` (default) · `equal_weight` · `quantum_qaoa` |
| `constraints.max_position` | float | Max weight per position (0–1) |
| `constraints.min_position` | float | Min weight per position (0–1) |

**Response `200`**
```json
{
  "current_allocation": {
    "AAPL": 0.435,
    "MSFT": 0.348,
    "GOOGL": 0.217
  },
  "target_allocation": {
    "AAPL": 0.40,
    "MSFT": 0.35,
    "GOOGL": 0.25
  },
  "recommended_trades": [
    { "ticker": "AAPL", "action": "SELL", "usd_amount": 804 },
    { "ticker": "GOOGL", "action": "BUY",  "usd_amount": 804 }
  ],
  "metrics": {
    "expected_sharpe": 1.24,
    "expected_return": 0.118,
    "expected_volatility": 0.095
  },
  "method": "mvo",
  "solver_time_ms": 43
}
```

---

### Backtest

#### `POST /backtest/run`

Run a strategy backtest on historical data.

**Request**
```json
{
  "ticker": "SPY",
  "start_date": "2020-01-01",
  "end_date": "2024-12-31",
  "strategy": {
    "type": "signal_follow",
    "signal_threshold": 0.65
  },
  "initial_capital": 100000
}
```

**Response `200`**
```json
{
  "ticker": "SPY",
  "period": { "start": "2020-01-01", "end": "2024-12-31" },
  "metrics": {
    "total_return": 0.412,
    "annualized_return": 0.072,
    "sharpe_ratio": 1.18,
    "max_drawdown": -0.143,
    "win_rate": 0.587,
    "total_trades": 48,
    "benchmark_return": 0.298
  },
  "equity_curve": [
    { "date": "2020-01-01", "value": 100000 },
    { "date": "2020-02-01", "value": 103200 }
  ]
}
```

---

### API Keys

#### `GET /keys`

List all API keys for the authenticated user.

**Response `200`**
```json
{
  "keys": [
    {
      "id": "uuid",
      "prefix": "sk_live_abc1",
      "name": "Production",
      "last_used_at": "2026-04-19T10:00:00Z",
      "created_at": "2026-01-01T00:00:00Z",
      "revoked": false
    }
  ]
}
```

#### `POST /keys`

Create a new API key. **Raw key shown only once — not stored.**

**Request**
```json
{ "name": "My trading bot" }
```

**Response `201`**
```json
{
  "id": "uuid",
  "key": "sk_live_xxxxxxxxxxxxxxxxxxxx",
  "prefix": "sk_live_xxxx",
  "name": "My trading bot"
}
```

#### `DELETE /keys/{id}`

Revoke an API key immediately.

**Response `204`** (no body)

---

### Usage

#### `GET /usage`

Return usage for the current billing period.

**Response `200`**
```json
{
  "plan": "pro",
  "period": {
    "start": "2026-04-01",
    "end": "2026-04-30"
  },
  "usage": {
    "api_calls": 4832,
    "limit": 10000,
    "signals": 2140,
    "portfolio_optimizations": 18,
    "backtests": 9
  },
  "estimated_bill_cents": 0
}
```

---

## Trading & operations (house book)

Read-only views of the worker-managed house book plus execution controls. These endpoints observe or steer the **single** internal book — not per-customer trading. Auth is the same API key as signals; internal-only actions also require `X-Internal-Secret` (must match `INTERNAL_SECRET` on API and worker).

```http
X-Internal-Secret: <same value as INTERNAL_SECRET>
Authorization: Bearer sk_live_...
```

| Header | When required |
|--------|----------------|
| `Authorization` | All endpoints below |
| `X-Internal-Secret` | `POST /execution/*` (except none on GET status), `POST /models/promotions/{id}/approve\|reject` |

---

### Positions

#### `GET /positions`

List open or recently closed positions from the `positions` table.

**Query params**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `asset_class` | string | — | `equity` · `crypto` · `option` · `forex` |
| `open_only` | bool | `true` | When `true`, only rows with `closed=false` |
| `limit` | int | 50 | Max rows (1–500) |

**Response `200`** — array of:

```json
{
  "id": "uuid",
  "asset_class": "equity",
  "symbol": "AAPL",
  "qty": 10.0,
  "entry_px": 185.42,
  "entry_ts": "2026-06-01T14:30:00Z",
  "current_px": 187.10,
  "unrealized_pnl": 16.80,
  "realized_pnl": 0.0,
  "closed": false,
  "closed_at": null
}
```

---

### Orders

#### `GET /orders`

Recent fills from the `orders` table (newest first).

**Query params**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `asset_class` | string | — | Filter by asset class |
| `symbol` | string | — | Filter (uppercased server-side) |
| `limit` | int | 50 | Max rows (1–500) |

**Response `200`** — array of:

```json
{
  "id": "uuid",
  "asset_class": "equity",
  "symbol": "AAPL",
  "ts": "2026-06-01T14:31:00Z",
  "side": "buy",
  "qty": 10.0,
  "px": 185.50,
  "fee": 0.0,
  "slippage_bps": 2.5,
  "executor": "alpaca",
  "external_id": "broker-order-id",
  "status": "filled"
}
```

---

### Execution

#### `GET /execution/status`

Current executor mode, per-class tick cadence defaults, and paused asset classes (from Redis).

**Response `200`**

```json
{
  "executor_mode": "paper",
  "coinbase_sandbox": true,
  "worker_asset_classes_default_crypto_seconds": 300,
  "worker_asset_classes_default_equity_seconds": 300,
  "worker_asset_classes_default_option_seconds": 900,
  "worker_asset_classes_default_forex_seconds": 300,
  "paused": ["forex"]
}
```

#### `POST /execution/run_cycle`

Run one worker tick on demand. **Internal-only.**

**Request**

```json
{ "asset_class": "equity" }
```

**Response `200`**

```json
{ "asset_class": "equity", "triggered": true }
```

#### `POST /execution/pause` · `POST /execution/resume`

Halt or resume one asset class without redeploying. **Internal-only.** Pause is stored in Redis; the worker skips ticks but keeps heartbeats (`status: paused`). See [`docs/RUNBOOK_WORKER.md`](./docs/RUNBOOK_WORKER.md).

**Request**

```json
{ "asset_class": "equity", "reason": "FOMC" }
```

**Response `200`**

```json
{ "asset_class": "equity", "paused": true }
```

#### `GET /execution/preflight` · `POST /execution/approve_live` · `POST /execution/revoke_live`

Go-live guardrail checks and session-scoped live-trading approval. **Internal-only.** Details in [`docs/GO_LIVE.md`](./docs/GO_LIVE.md).

---

### Strategies (performance)

Aggregates from `signal_history.component_weights` — contribution frequency, strength, and win rate above a threshold for labeled rows.

#### `GET /strategies/performance`

**Query params**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `asset_class` | string | `equity` | `equity` · `crypto` · `forex` · `option` |
| `period` | string | — | Rolling window, e.g. `7d`, `24h` (overrides `since`) |
| `since` | ISO datetime | — | Only signals after this time |
| `strength_threshold` | float | `0.3` | Min strategy strength for win-rate bucket |
| `limit` | int | 5000 | Max signal rows scanned (1–50000) |

**Response `200`**

```json
{
  "asset_class": "equity",
  "period": "7d",
  "since": "2026-05-26T00:00:00+00:00",
  "strength_threshold": 0.3,
  "n_signals": 1200,
  "n_labeled": 800,
  "strategies": [
    {
      "strategy": "ict",
      "n_signals": 1200,
      "contribution_count": 400,
      "contribution_frequency": 0.3333,
      "avg_strength_when_present": 0.45,
      "n_above_threshold": 120,
      "n_labeled_above_threshold": 90,
      "win_rate_above_threshold": 0.52,
      "avg_realized_return_above_threshold": 0.0012
    }
  ],
  "summary": "# Strategy report — equity (7d)\n..."
}
```

#### `GET /strategies/performance/report`

Same stats as `/performance` with `period` defaulting to `7d` and markdown `summary` always included. Use for weekly M1 review (dashboard: `/strategies`).

---

### Models (lifecycle)

Human-approval surface for champion promotions. GETs use API key only; approve/reject require internal secret.

#### `GET /models/champions`

Active model version per `(asset_class, model_type)`.

```json
[
  {
    "asset_class": "equity",
    "model_type": "ensemble",
    "version": "v1.0",
    "updated_at": "2026-06-01T00:00:00Z"
  }
]
```

#### `GET /models/promotions`

**Query:** `status` = `pending` | `approved` | `rejected`, `limit` (default 50).

#### `GET /models/evaluations`

**Query:** `asset_class`, `model_version`, `limit`.

#### `GET /models/promotions/{id}/report`

Candidate vs incumbent metrics, deltas, markdown `summary`, and `recommendation` (`review` | `candidate_leads` | `promoted` | `rejected`).

#### `POST /models/promotions/{id}/approve` · `POST /models/promotions/{id}/reject`

**Internal-only.** Activates or declines a pending promotion; worker picks up champion from `model_champions` on next tick.

---

### Worker health

#### `GET /health/worker`

No API key required. Liveness from Redis heartbeats written each tick.

**Response `200`**

```json
{
  "status": "ok",
  "workers": {
    "equity": {
      "ts": "2026-06-02T15:00:00+00:00",
      "status": "ok",
      "duration_s": 12.4,
      "age_seconds": 45.2,
      "stale": false,
      "paused": false,
      "healthy": true
    }
  },
  "opend": { "reachable": true, "ts": "..." }
}
```

`status` is `degraded` if any class is stale or in error; `unknown` if no heartbeats exist. Paused classes count as healthy when fresh.

---

## Error Format

All errors return consistent JSON:

```json
{
  "detail": "Human-readable error message",
  "code": "RATE_LIMIT_EXCEEDED",
  "docs": "https://sigma.dev/docs/errors#rate-limit"
}
```

| HTTP Status | Code | Meaning |
|-------------|------|---------|
| 400 | `BAD_REQUEST` | Malformed request body |
| 401 | `INVALID_API_KEY` | Missing or invalid API key |
| 404 | `NOT_FOUND` | Resource doesn't exist |
| 422 | `VALIDATION_ERROR` | Invalid field values |
| 429 | `RATE_LIMIT_EXCEEDED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Server error — reported to Sentry |
| 503 | `SERVICE_UNAVAILABLE` | Quantum backend / ML model unavailable |
