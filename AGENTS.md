# AGENTS.md

## Learned User Preferences

- When given a plan to implement, never edit the plan file itself; treat it as read-only reference.
- Use the to-dos already created from the plan; do not recreate them, and mark them `in_progress` sequentially as work progresses.
- Run all to-dos to completion in one pass; do not stop partway through a planned slice.
- Keep `docs/ROADMAP.md` in sync with implementation progress (check off items as they ship). It is the single source of truth for milestones/sprints/backlog.
- Treat the numbered docs (`00_QUICKSTART`–`05_API_REFERENCE`) plus `docs/ROADMAP.md`, `docs/MODELS.md`, and `DEPLOY.md`/`DEPLOY_EQUITY.md` as the source of truth for scope; verify against them before inventing structure or APIs.

## Learned Workspace Facts

- Repo is `sigma`, a monorepo for an AI/quantum signals + portfolio-optimizer SaaS.
- Layout: `apps/web/` (Next.js 16 frontend + API gateway), `apps/api/` (FastAPI Python backend), `packages/db/`, `packages/types/`, plus `tests/`, `scripts/`, `docker-compose.yml`, `Makefile`.
- Frontend stack: TypeScript 5.x, Next.js 16, React 19, Tailwind CSS; auth via Clerk; billing via Stripe.
- Backend stack: Python 3.12, FastAPI, Pydantic v2; ML/quantum via pandas-ta, PyTorch, scikit-learn, XGBoost, CVXPY, Qiskit, PennyLane. Equity market data via Alpaca → Tiingo (fallback); crypto via Coinbase public candles.
- Execution: Alpaca (equities, alpaca-py) and Coinbase Advanced Trade (crypto), behind a per-asset Executor with OrderIntent → ExecutionReport and DB-backed idempotency.
- Data layer: PostgreSQL 15 with the TimescaleDB extension; Redis 7 for cache + rate limiting + worker heartbeat/singleton lock.
- Deployment targets: Vercel (web) and Fly.io (`sigma-api` + `sigma-worker`); Postgres on Timescale Cloud, Redis on Upstash.
- Local dev runs via `docker compose up -d` (Postgres + TimescaleDB + Redis); workflow shortcuts live in `Makefile` (`make dev`, `make test`, `make migrate`).
- Project planning docs live under `docs/`: `00_QUICKSTART.md`–`05_API_REFERENCE.md`, `ROADMAP.md`, `MODELS.md`, `DEPLOY_EQUITY.md`, plus `DEPLOY.md` and `README.md` at the repo root.
- Roadmap is structured as a 4-week build (Week 1 foundation → Week 4 docs/polish/launch); each week is delivered as a discrete plan-driven slice.
