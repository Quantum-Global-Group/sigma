# SIGMA — Environment Variables

> Copy `.env.example` to `.env.local` (web) and `.env` (api). Never commit real values.

---

## Where Each Group Lives

```mermaid
flowchart LR
  subgraph webenv ["apps/web/.env.local"]
    WCLERK[Clerk pk/sk + URLs]
    WSTRIPE[Stripe pk + webhook + prices]
    WAPI[NEXT_PUBLIC_API_URL]
  end
  subgraph apienv ["apps/api/.env"]
    ACORE[App + SECRET_KEY]
    ADATA[DATABASE_URL + REDIS_URL]
    AAUTH[Clerk sk + JWT]
    ABILL[Stripe sk + meter]
    AML[Model dir + quantum + HF]
    AOBS[Sentry + Langfuse]
  end
  WAPI -->|REST| apienv
  WCLERK -. verifies JWT .-> AAUTH
  WSTRIPE -. same secret .-> ABILL
```

| Surface | File | Key groups |
| --- | --- | --- |
| Frontend + gateway | `apps/web/.env.local` | Clerk, Stripe (public), backend URL |
| Backend | `apps/api/.env` | App, DB, Redis, Clerk, Stripe (secret), ML, quantum, observability, rate limits |

---

## `apps/web/.env.local`

```env
# ─── Clerk (auth) ────────────────────────────────────────────────
# Get from: dashboard.clerk.com → API Keys
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/dashboard
NEXT_PUBLIC_CLERK_AFTER_SIGN_UP_URL=/dashboard

# ─── Stripe ──────────────────────────────────────────────────────
# Get from: dashboard.stripe.com → Developers → API Keys
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
# Get from: dashboard.stripe.com → Developers → Webhooks
STRIPE_WEBHOOK_SECRET=whsec_...
# Get from: dashboard.stripe.com → Products → Prices
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_ENTERPRISE=price_...

# ─── Backend API ─────────────────────────────────────────────────
# Local: http://localhost:8000 | Prod: your Railway URL
NEXT_PUBLIC_API_URL=http://localhost:8000

# ─── App ─────────────────────────────────────────────────────────
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

---

## `apps/api/.env`

```env
# ─── App ─────────────────────────────────────────────────────────
ENVIRONMENT=development             # development | production
DEBUG=true
API_PORT=8000
SECRET_KEY=your-random-256-bit-secret-key-here

# ─── Database ────────────────────────────────────────────────────
# Local (Docker Compose): postgresql+asyncpg://postgres:password@localhost:5432/sigma
# Prod (Railway): provided automatically as DATABASE_URL
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/sigma
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# ─── Redis ───────────────────────────────────────────────────────
# Local (Docker Compose): redis://localhost:6379
# Prod (Railway): provided automatically as REDIS_URL
REDIS_URL=redis://localhost:6379
REDIS_TTL_SIGNAL=3600               # Signal cache TTL seconds (1 hour)
REDIS_TTL_API_KEY=86400             # API key cache TTL seconds (24 hours)

# ─── Stripe ──────────────────────────────────────────────────────
# Same key as web — backend needs it for metering
STRIPE_SECRET_KEY=sk_test_...
# Get from: dashboard.stripe.com → Billing → Meters
STRIPE_METER_ID=mtr_...             # "api_calls" meter ID

# ─── Clerk ───────────────────────────────────────────────────────
# Backend needs this to verify JWTs from frontend
CLERK_SECRET_KEY=sk_test_...
CLERK_JWT_KEY=...                   # Get from Clerk dashboard → JWT Templates

# ─── Market Data ─────────────────────────────────────────────────
# Equity OHLCV: Alpaca primary, Tiingo fallback (comma-separated order)
EQUITY_DATA_PROVIDERS=alpaca,tiingo
TIINGO_API_KEY=                     # Tiingo token — https://www.tiingo.com/account/api/token

# ─── ML Models ───────────────────────────────────────────────────
MODEL_DIR=./ml/saved_models         # Where trained .pkl / .pt files live
MODEL_VERSION=v1.0
MLFLOW_TRACKING_URI=                # Optional; defaults to local sqlite under apps/api

# pgvector signal embeddings (worker scheduler — default off)
EMBED_SIGNALS_ENABLED=false         # Nightly embed job in apps/worker/scheduler.py
EMBED_SIGNALS_INTERVAL_HOURS=24
EMBED_SIGNALS_LIMIT=1000

# ─── Quantum ─────────────────────────────────────────────────────
# IBM Quantum (already configured in your environment)
IBM_QUANTUM_TOKEN=                  # From quantum.ibm.com → Account
IBM_QUANTUM_INSTANCE=               # e.g. ibm-q/open/main
IBM_QUANTUM_BACKEND=ibm_brisbane    # Default backend

# ─── HuggingFace ─────────────────────────────────────────────────
# Get from: huggingface.co → Settings → Access Tokens
HUGGINGFACE_TOKEN=hf_...

# ─── Observability ───────────────────────────────────────────────
# Sentry: sentry.io → New Project → Python
SENTRY_DSN=https://...@sentry.io/...
# Langfuse: cloud.langfuse.com → Settings → API Keys
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# ─── Rate Limits ─────────────────────────────────────────────────
RATE_LIMIT_FREE=100                 # calls per day on free tier
RATE_LIMIT_PRO=10000                # calls per day on pro tier
RATE_LIMIT_ENTERPRISE=1000000       # calls per day on enterprise tier
```

---

## Where to Get Each Key

| Variable | Service | URL |
|----------|---------|-----|
| `CLERK_*` | Clerk | [dashboard.clerk.com](https://dashboard.clerk.com) |
| `STRIPE_*` | Stripe | [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) |
| `STRIPE_WEBHOOK_SECRET` | Stripe | [dashboard.stripe.com/webhooks](https://dashboard.stripe.com/webhooks) |
| `STRIPE_METER_ID` | Stripe | [dashboard.stripe.com/billing/meters](https://dashboard.stripe.com/billing/meters) |
| `IBM_QUANTUM_TOKEN` | IBM Quantum | [quantum.ibm.com/account](https://quantum.ibm.com/account) |
| `HUGGINGFACE_TOKEN` | Hugging Face | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `SENTRY_DSN` | Sentry | [sentry.io](https://sentry.io) → New Project → Python/Next.js |
| `LANGFUSE_*` | Langfuse | [cloud.langfuse.com](https://cloud.langfuse.com) |

---

## Railway Deployment

Railway auto-injects `DATABASE_URL` and `REDIS_URL` when you attach services.
Override via: **Railway dashboard → Service → Variables → Add Variable**

```bash
# Push all local vars to Railway at once:
railway variables set --from-env .env
```
