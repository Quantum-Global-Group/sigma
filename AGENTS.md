# AGENTS.md

## Learned User Preferences

- When given a plan to implement, never edit the plan file itself; treat it as read-only reference.
- Use the to-dos already created from the plan; do not recreate them, and mark them `in_progress` sequentially as work progresses.
- Run all to-dos to completion in one pass; do not stop partway through a planned slice.
- Keep `06_ROADMAP.md` in sync with implementation progress (check off items as they ship).
- Treat the numbered docs (`00_QUICKSTART`–`06_ROADMAP`) as the source of truth for scope; verify against them before inventing structure or APIs.

## Learned Workspace Facts

- Repo is `sigma`, a monorepo for an AI/quantum signals + portfolio-optimizer SaaS.
- Layout: `apps/web/` (Next.js 15 frontend + API gateway), `apps/api/` (FastAPI Python backend), `packages/db/`, `packages/types/`, plus `tests/`, `scripts/`, `docker-compose.yml`, `Makefile`.
- Frontend stack: TypeScript 5.x, Next.js 15, React 19, Tailwind CSS; auth via Clerk; billing via Stripe.
- Backend stack: Python 3.11+, FastAPI, Pydantic v2; ML/quantum via yfinance, pandas-ta, PyTorch, scikit-learn, CVXPY, Qiskit, PennyLane.
- Data layer: PostgreSQL 15 with the TimescaleDB extension; Redis 7 for cache + rate limiting.
- Deployment targets: Vercel (web) and Railway (FastAPI + Postgres + Redis).
- Local dev runs via `docker compose up -d` (Postgres + TimescaleDB + Redis); workflow shortcuts live in `Makefile` (`make dev`, `make test`, `make migrate`).
- Project planning is organized as numbered docs at repo root: `00_QUICKSTART.md`, `01_TECH_STACK.md`, `02_PROJECT_STRUCTURE.md`, `03_ENV_VARS.md`, `04_DATABASE_SCHEMA.md`, `05_API_REFERENCE.md`, `06_ROADMAP.md`, plus `DEPLOY.md` and `README.md`.
- Roadmap is structured as a 4-week build (Week 1 foundation → Week 4 docs/polish/launch); each week is delivered as a discrete plan-driven slice.
