# packages/db

SQL migrations for SIGMA (PostgreSQL 15 + TimescaleDB).

## Running migrations

From the repo root after `docker compose up -d`:

```bash
make migrate
```

Or manually:

```bash
docker compose exec -T postgres psql -U postgres -d sigma -f /migrations/001_initial_schema.sql
docker compose exec -T postgres psql -U postgres -d sigma -f /migrations/002_timescaledb.sql
docker compose exec -T postgres psql -U postgres -d sigma -f /migrations/003_billing_events.sql
```

## Rules

- Never edit an existing migration file — always add a new numbered file.
- Use `IF NOT EXISTS` / `if_not_exists => TRUE` so migrations are idempotent.
- Migrations are mounted read-only into the Postgres container at `/migrations`.
