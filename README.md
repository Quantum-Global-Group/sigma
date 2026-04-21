# SIGMA

AI-powered trading signals with quantum portfolio optimization.

**Quick start → [00_QUICKSTART.md](00_QUICKSTART.md)**

## Docs

| File | Contents |
|------|----------|
| [00_QUICKSTART.md](00_QUICKSTART.md) | Get the dev environment running in under 30 minutes |
| [01_TECH_STACK.md](01_TECH_STACK.md) | Technology choices and rationale |
| [02_PROJECT_STRUCTURE.md](02_PROJECT_STRUCTURE.md) | Every file and directory, build order by week |
| [03_ENV_VARS.md](03_ENV_VARS.md) | All environment variables documented |
| [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) | PostgreSQL + TimescaleDB schema + migrations |
| [05_API_REFERENCE.md](05_API_REFERENCE.md) | REST API endpoints, auth, rate limits |
| [06_ROADMAP.md](06_ROADMAP.md) | Weekly task list with done conditions |

## Stack summary

```
Languages:   TypeScript (frontend) + Python 3.11 (ML/backend)
Frontend:    Next.js 15 + Tailwind + shadcn/ui
Backend:     FastAPI + Pydantic v2
ML:          scikit-learn + yfinance + pandas-ta  (PyTorch/quantum in Week 3)
Data:        PostgreSQL + TimescaleDB + Redis
Auth:        Clerk
Payments:    Stripe
Deploy:      Vercel (frontend) + Railway (backend + DB)
```
