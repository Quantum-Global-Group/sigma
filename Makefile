.PHONY: dev dev-api dev-web migrate seed test lint format logs clean help package-gumroad load-test worker worker-local train-ranking e2e e2e-down

MIGRATIONS_DIR := packages/db/migrations
PG_USER        := postgres
PG_DB          := sigma

help:
	@echo "SIGMA — available targets:"
	@echo "  make dev      Start Docker services (run API + web manually in separate terminals)"
	@echo "  make dev-api  Start FastAPI on 0.0.0.0:\$$API_PORT (default 8001)"
	@echo "  make dev-web  Start Next.js on 0.0.0.0:\$$WEB_PORT (default 3001)"
	@echo "  make migrate  Apply database migrations in order"
	@echo "  make seed     Seed dev database with test data"
	@echo "  make test     Run all tests (Python + TypeScript type-check)"
	@echo "  make lint     Lint Python (ruff) + TypeScript (eslint)"
	@echo "  make format   Format Python (black) + TypeScript (prettier)"
	@echo "  make logs     Tail all Docker logs"
	@echo "  make clean    Stop Docker + remove volumes (WARNING: deletes data)"
	@echo "  make package-gumroad  Build dist/gumroad/*.zip bundles for upload"
	@echo "  make load-test        Run Locust against SIGMA_LOADTEST_BASE_URL"
	@echo "  make worker           Start the live trading worker in Docker (uses --profile worker)"
	@echo "  make worker-local     Run the worker directly against local Postgres+Redis"
	@echo "  make train-ranking    Fetch Coinbase history and fit the crypto RankingModel"
	@echo "  make e2e              Real end-to-end smoke vs local Postgres+Redis (offline, paper)"

dev:
	docker compose up -d
	@echo ""
	@echo "Docker services running. Start servers in separate terminals:"
	@echo "  Terminal 1:  make dev-api"
	@echo "  Terminal 2:  make dev-web"
	@echo ""
	@echo "Split-server: set NEXT_PUBLIC_API_URL on the web host and CORS_ORIGINS on the API host."

dev-api:
	cd apps/api && .venv/bin/uvicorn main:app --reload --host $${API_HOST:-0.0.0.0} --port $${API_PORT:-8001}

dev-web:
	cd apps/web && npm run dev -- -H 0.0.0.0 -p $${WEB_PORT:-3001}

migrate:
	@echo "Running migrations..."
	@for f in $(MIGRATIONS_DIR)/*.sql; do \
		echo "  Applying $$f ..."; \
		docker compose exec -T postgres psql -U $(PG_USER) -d $(PG_DB) -f "/migrations/$$(basename $$f)"; \
	done
	@echo "Migrations complete."

seed:
	cd apps/api && python scripts/seed_db.py

test:
	cd apps/api && pytest -v
	cd apps/web && npm run type-check

lint:
	cd apps/api && ruff check .
	cd apps/web && npm run lint

format:
	cd apps/api && black .
	cd apps/web && npm run format

logs:
	docker compose logs -f

clean:
	docker compose down -v

package-gumroad:
	bash scripts/package_gumroad_assets.sh

load-test:
	@if [ -z "$$SIGMA_LOADTEST_BASE_URL" ]; then \
		echo "ERROR: set SIGMA_LOADTEST_BASE_URL (and SIGMA_LOADTEST_API_KEY for /signals)"; exit 1; \
	fi
	locust -f tests/load_test.py --host "$$SIGMA_LOADTEST_BASE_URL"

worker:
	docker compose --profile worker up -d --build worker
	docker compose logs -f worker

worker-local:
	cd apps/api && PYTHONPATH=. python -m worker.main

train-ranking:
	cd apps/api && PYTHONPATH=. python scripts/train_ranking.py $(ARGS)

# Real end-to-end proof: brings up Postgres+Redis, applies migrations, seeds, and
# runs the offline smoke (synthetic data + paper executor) — asserting real rows
# land in every table. No external creds. See docs/E2E_VALIDATION.md.
e2e:
	docker compose up -d postgres redis
	@echo "Waiting for Postgres..."
	@until docker compose exec -T postgres pg_isready -U $(PG_USER) -d $(PG_DB) >/dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate
	$(MAKE) seed
	cd apps/api && DATABASE_URL=postgresql+asyncpg://$(PG_USER):password@localhost:5432/$(PG_DB) \
		REDIS_URL=redis://localhost:6379 PYTHONPATH=. python scripts/e2e_smoke.py --clean

e2e-down:
	docker compose stop postgres redis

