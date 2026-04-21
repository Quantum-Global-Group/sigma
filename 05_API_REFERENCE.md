# SIGMA — API Reference

> Base URL: `https://api.sigma.dev` (prod) | `http://localhost:8000` (local)
> All endpoints require `Authorization: Bearer YOUR_API_KEY` header unless noted.

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
