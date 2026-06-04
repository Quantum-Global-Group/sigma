# SIGMA — Account Connections Reference

All external accounts, what they're used for, how they're configured, and how
to verify connectivity. Paper-first by default; every venue has an independent
live guard that must be deliberately enabled.

---

## Account Inventory

| Venue | Asset Class | Use | DGX `.env` | Paper | Live Guard |
|---|---|---|---|---|---|
| **Alpaca** | Equities | Execution + OHLCV data (primary) | `ALPACA_API_KEY`, `ALPACA_SECRET` | `ALPACA_PAPER=true` | `ALPACA_ALLOW_LIVE=false` |
| **Tiingo** | Equities | OHLCV data (fallback when Alpaca data fails) | `TIINGO_API_KEY` | N/A (data only) | N/A |
| **OANDA** | Forex | Execution + OHLCV (primary forex, superseded per-symbol by MT5) | `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID` | `OANDA_PAPER=true`, `OANDA_ENVIRONMENT=practice` | `OANDA_ALLOW_LIVE=false` |
| **BlackBull MT5** | Forex / CFD | Execution + OHLCV via EvoX2 bridge | `MT5_BRIDGE_URL`, `MT5_BRIDGE_SECRET` | `MT5_PAPER=true` | `MT5_ALLOW_LIVE=false` |
| **Moomoo / OpenD** | Options | Execution + chain data via EvoX2 gateway | `MOOMOO_HOST`, `MOOMOO_PORT` | `MOOMOO_PAPER=true` | `MOOMOO_ALLOW_LIVE=false` |
| **Coinbase** | Crypto | Execution (not yet configured) | `COINBASE_API_KEY_NAME`, `COINBASE_PRIVATE_KEY` | `COINBASE_SANDBOX=true` | Live keys + sandbox=false |
| **Timescale Cloud** | — | Postgres 15 + TimescaleDB + pgvector | `DATABASE_URL` | N/A | N/A |
| **Upstash Redis** | — | Cache, rate-limits, worker singleton lock, heartbeats | `REDIS_URL` | N/A | N/A |
| **Clerk** | — | Auth (stub — not yet configured) | `CLERK_SECRET_KEY` | N/A | N/A |
| **Stripe** | — | Billing (stub — not yet configured) | `STRIPE_SECRET_KEY` | N/A | N/A |

---

## Architecture

```
┌─ DGX Spark (192.168.0.32) ──────────────────────────────────┐
│  sigma-worker (equity + forex + options)                     │
│  ├── Alpaca (equity data + execution) ─── HTTPS ──► Alpaca  │
│  ├── Tiingo (equity fallback data) ────── HTTPS ──► Tiingo  │
│  ├── MT5 bridge (forex data + exec) ───── HTTP ──► EvoX2    │
│  └── Moomoo SDK (options data + exec) ─── TCP ───► EvoX2    │
│                                                              │
│  sigma-api (FastAPI)                                         │
│  ├── Timescale Cloud (Postgres) ────────── SSL ──► Cloud    │
│  └── Upstash Redis ─────────────────────── TLS ──► Cloud    │
│                                                              │
│  sigma-web (Next.js 16)                                      │
│                                                              │
└──────────────────────────────────────────────────────────────┘

┌─ EvoX2 Windows (192.168.0.26) ──────────────────────────────┐
│  MetaTrader 5 (BlackBull demo)                               │
│  services/mt5-bridge (:8787)                                 │
│  Moomoo OpenD (:11111)                                       │
└──────────────────────────────────────────────────────────────┘
```

---

## Alpaca — Equities (paper)

**Status:** ✅ Active

Alpaca is the primary equity execution venue and OHLCV data provider. The
worker places fractional-share market orders through `alpaca-py` (the modern
SDK). Tiingo is configured as a fallback data provider if Alpaca data fails.

**Required env vars** (`apps/api/.env`):

```env
ALPACA_API_KEY=PKUH3IKNHGVTOOFHN5B3WHLSVH
ALPACA_SECRET=5Junvvaacbe5xAK4aVqQ3L5c6VLwhf9diDWDucej8sqc
ALPACA_PAPER=true
ALPACA_ALLOW_LIVE=false
ALPACA_DATA_FEED=iex
EQUITY_EXECUTOR=alpaca
```

**Verification:**

```bash
cd apps/api
.venv/bin/python -c "
from alpaca.trading.client import TradingClient
from config import settings
c = TradingClient(settings.alpaca_api_key, settings.alpaca_secret, paper=True)
a = c.get_account()
print(f'equity=\${float(a.equity):.2f} buying_power=\${float(a.buying_power):.2f}')
"
```

Expected output: `equity=$2531.30 buying_power=$8137.54`

**Dashboard:** https://app.alpaca.markets/paper (log in with your Alpaca credentials).

**Live guard:** Set `ALPACA_ALLOW_LIVE=true` AND `ALPACA_PAPER=false` to enable
live trading. Do not do this before M3.

---

## Tiingo — Equity Market Data (fallback)

**Status:** ✅ Active

Tiingo provides daily OHLCV bars as a fallback when Alpaca data is unavailable.
The `EQUITY_DATA_PROVIDERS` setting controls the provider order (left = tried first).

**Required env vars:**

```env
TIINGO_API_KEY=a83215852f73ecec650f7c54ba65c3599667c800
EQUITY_DATA_PROVIDERS=alpaca,tiingo
```

**Verification:**

```bash
curl -s "https://api.tiingo.com/tiingo/daily/AAPL/prices?token=$TIINGO_API_KEY&resampleFreq=daily&startDate=2026-06-01" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{len(d)} daily bars, last close=\${d[-1][\"close\"]}')"
```

---

## OANDA — Forex (practice)

**Status:** ✅ Active (practice account, $100K NAV)

OANDA provides forex OHLCV and execution via the `oandapyV20` SDK. It operates
in `practice` environment (paper). Symbols not listed in `FOREX_MT5_SYMBOLS`
route through OANDA; the rest route through the MT5 bridge.

**Required env vars:**

```env
OANDA_API_TOKEN=d02f6cd08240e7f0ec8402eaffba2f23-262d44a4887fdc6cc648a28fd9f963f6
OANDA_ACCOUNT_ID=101-001-39476740-001
OANDA_ENVIRONMENT=practice
OANDA_PAPER=true
OANDA_ALLOW_LIVE=false
FOREX_EXECUTOR=oanda
```

**Verification:**

```bash
cd apps/api
.venv/bin/python -c "
import oandapyV20.endpoints.accounts as a, oandapyV20 as v20
from config import settings
c = v20.API(access_token=settings.oanda_api_token, environment=settings.oanda_environment)
r = a.AccountDetails(settings.oanda_account_id)
print(f'balance=\${float(c.request(r)[\"account\"][\"balance\"]):.2f}')
"
```

Expected: `balance=$99976.61`

**Live guard:** Requires `OANDA_ALLOW_LIVE=true` AND `OANDA_PAPER=false` AND
`OANDA_ENVIRONMENT=live`.

---

## BlackBull MT5 Bridge — Forex / CFD (demo)

**Status:** 🔧 Requires bridge service on EvoX2

MT5 runs on the EvoX2 Windows machine (192.168.0.26) beside a logged-in
BlackBull demo terminal. The sigma worker on DGX talks to it via an HTTP bridge.
All forex symbols route through MT5 (`FOREX_EXECUTOR=mt5`).

**Bridge setup** — run on EvoX2 per [`EVOX2_SETUP.md`](EVOX2_SETUP.md).

**Required env vars** (DGX `apps/api/.env`):

```env
MT5_BRIDGE_URL=http://192.168.0.26:8787
MT5_BRIDGE_SECRET=f67825f066cc19466fae306fed990a6883050d9801fcf04efd902bdf309a46cf
MT5_BRIDGE_TIMEOUT_SECONDS=10
MT5_PAPER=true
MT5_ALLOW_LIVE=false
MT5_QTY_IS_LOTS=false
MT5_UNITS_PER_LOT=100000
FOREX_EXECUTOR=mt5
FOREX_UNIVERSE=EUR_USD,GBP_USD,AUD_USD,USD_JPY,USD_CAD,XAUUSD
```

**Required env vars** (EvoX2 `services/mt5-bridge/.env`):

```env
MT5_BRIDGE_HOST=0.0.0.0
MT5_BRIDGE_PORT=8787
MT5_BRIDGE_SECRET=f67825f066cc19466fae306fed990a6883050d9801fcf04efd902bdf309a46cf
MT5_LOGIN=<your-blackbull-demo-login>
MT5_PASSWORD=<your-password>
MT5_SERVER=BlackBullMarkets-Demo
MT5_PAPER=true
```

**Verification** (from DGX, when bridge is running):

```bash
cd apps/api
MT5_BRIDGE_URL=http://192.168.0.26:8787 MT5_BRIDGE_SECRET=f67825f066cc19466fae306fed990a6883050d9801fcf04efd902bdf309a46cf \
  .venv/bin/python scripts/check_mt5_bridge.py --symbol XAUUSD
```

**Live guard:** `MT5_ALLOW_LIVE=false` (must be true + `MT5_PAPER=false`).
Workers skip MT5-routed symbols when the bridge health probe fails; OANDA
symbols (if any) continue unaffected.

**MT5 symbols traded:**

| Symbol | Description |
|--------|-------------|
| `XAUUSD` | Gold vs USD |

Additional symbols in `FOREX_UNIVERSE` (EUR_USD, GBP_USD, AUD_USD, USD_JPY,
USD_CAD) also route through MT5 when `FOREX_EXECUTOR=mt5`.

---

## Moomoo / OpenD — Options (paper)

**Status:** 🔧 Requires OpenD gateway on EvoX2

Moomoo provides US options chain data and execution through the OpenD gateway
daemon. The gateway runs on EvoX2 (192.168.0.26) and the sigma worker's Moomoo
SDK connects to it over the LAN. Options cannot run on Fly — the SDK requires a
local TCP daemon.

**OpenD setup** — run on EvoX2 per [`EVOX2_SETUP.md`](EVOX2_SETUP.md).

**Required env vars:**

```env
OPTION_EXECUTOR=moomoo
MOOMOO_HOST=192.168.0.26
MOOMOO_PORT=11111
MOOMOO_TRD_MARKET=US
MOOMOO_SECURITY_FIRM=FUTUINC
MOOMOO_PAPER=true
MOOMOO_ALLOW_LIVE=false
OPEND_CHECK_ENABLED=true
OPEND_RESTART_COMMAND=
OPTION_UNIVERSE=AAPL,MSFT,NVDA,SPY,QQQ
```

**Verification** (from DGX, when OpenD is running):

```bash
cd apps/api
MOOMOO_HOST=192.168.0.26 .venv/bin/python scripts/check_moomoo_opend.py
```

**Options universe:**

| Ticker | Description |
|--------|-------------|
| `AAPL` | Apple |
| `MSFT` | Microsoft |
| `NVDA` | NVIDIA |
| `SPY` | SPDR S&P 500 ETF |
| `QQQ` | Invesco QQQ Trust (Nasdaq-100) |

All five are underlyings with liquid option chains for the options pipeline.

**Live guard:** `MOOMOO_ALLOW_LIVE=false` (must be true + `MOOMOO_PAPER=false`).

---

## Coinbase — Crypto (paper / not configured)

**Status:** ⏸️ Paper only; live keys not configured

Crypto uses `CRYPTO_EXECUTOR=paper` which simulates fills in Postgres. No
broker keys have been set up yet. When ready, Coinbase Advanced Trade API
keys are configured with:

```env
CRYPTO_EXECUTOR=coinbase
COINBASE_API_KEY_NAME=<your-key-name>
COINBASE_PRIVATE_KEY=<ecdsa-private-key>
COINBASE_SANDBOX=true
```

Crypto signals and the `CRYPTO_UNIVERSE` (BTC-USD, ETH-USD, SOL-USD, LINK-USD,
AVAX-USD) are ready but do not trigger orders until the executor flips from
`paper` to `coinbase`. The crypto RankingModel can be trained via
`scripts/train_ranking.py`.

---

## Clerk — Auth (stub)

**Status:** ❌ Stub keys — not functional

Clerk provides authentication for the web dashboard. The `.env` contains stub
keys (`pk_test_REPLACE_ME`, `sk_test_REPLACE_ME`). The web app renders pages
but sign-in/sign-up flows will not work.

To enable auth, replace these with real keys from https://dashboard.clerk.com:

```env
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_<real>
CLERK_SECRET_KEY=sk_test_<real>
CLERK_WEBHOOK_SECRET=whsec_<real>
CLERK_JWT_KEY=<PEM public key from JWT template>
```

---

## Stripe — Billing (stub)

**Status:** ❌ Stub keys — not functional

Stripe handles usage metering and payments. The `.env` contains stub keys. No
metering records are sent until real keys are configured.

---

## Infrastructure — Database & Cache

### Timescale Cloud (Postgres)

**Status:** ✅ Active — service `e25vkdi72j` (db-94003)

```env
DATABASE_URL=postgresql+asyncpg://tsdbadmin:<password>@e25vkdi72j.clvhjgpm77.tsdb.cloud.timescale.com:38722/tsdb?ssl=require
```

Extensions enabled: `timescaledb` (migration 002), `vector` (migration 012).

**Verification:**

```bash
cd apps/api
.venv/bin/python -c "import asyncio, asyncpg; asyncio.run(asyncpg.connect('postgresql://tsdbadmin:q9bxus6cogxq652s@e25vkdi72j.clvhjgpm77.tsdb.cloud.timescale.com:38722/tsdb?ssl=require'))"
```

Or via the `/ready` endpoint:

```bash
curl -s http://localhost:8001/ready | python3 -c "import sys,json; print(json.load(sys.stdin))"
```

### Upstash Redis

**Status:** ✅ Active — instance `heroic-mayfly-141981`

```env
REDIS_URL=rediss://default:<token>@heroic-mayfly-141981.upstash.io:6379
```

Used for: API key cache, signal cache, rate-limits, worker singleton lock,
worker heartbeats, scheduler heartbeat.

**Verification:**

```bash
cd apps/api
.venv/bin/python -c "import asyncio, redis.asyncio as r; asyncio.run(r.from_url('$(grep ^REDIS_URL .env | cut -d= -f2-)', decode_responses=True).ping())"
```
