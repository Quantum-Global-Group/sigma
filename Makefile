.PHONY: dev migrate seed test lint format logs clean help package-gumroad load-test worker worker-local

MIGRATIONS_DIR := packages/db/migrations
PG_USER        := postgres
PG_DB          := sigma

help:
	@echo "SIGMA — available targets:"
	@echo "  make dev      Start Docker services (run API + web manually in separate terminals)"
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

dev:
	docker compose up -d
	@echo ""
	@echo "Docker services running. Start servers in separate terminals:"
	@echo "  Terminal 1:  cd apps/api && uvicorn main:app --reload --port 8000"
	@echo "  Terminal 2:  cd apps/web && npm run dev"

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

