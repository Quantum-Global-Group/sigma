-- 013_trading_accounts.sql
--
-- Multi-account foundation (Tier 3.1 + 3.2):
--   * trading_accounts — one row per (user, broker) trading relationship.
--   * account_id (NOT NULL, FK) on positions, orders, exit_state so every
--     position/order/exit is attributable to exactly one account.
--   * Idempotency key widened to (account_id, client_order_id) so two accounts
--     can place the "same" logical order without colliding.
--
-- Backward-compatible: a deterministic "house" account is seeded and every
-- existing row is backfilled to it, so the single-house-book worker keeps
-- working unchanged. The house account uses broker='house', a sentinel the
-- executor factory maps back to the legacy per-asset-class env resolution
-- (crypto→coinbase, equity→alpaca). Real per-broker accounts map broker
-- directly. Per-account credentials are deferred to 3.3 (vault); until then all
-- accounts share the global broker env, so DB books are isolated but broker-side
-- independence requires 3.3.

-- ---------------------------------------------------------------------------
-- trading_accounts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS trading_accounts (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  broker                VARCHAR(32) NOT NULL,                      -- house | paper | alpaca | coinbase | moomoo
  label                 VARCHAR(100),
  paper                 BOOLEAN NOT NULL DEFAULT TRUE,             -- paper vs live
  enabled_asset_classes VARCHAR(64) NOT NULL DEFAULT 'crypto,equity',  -- comma list
  status                VARCHAR(16) NOT NULL DEFAULT 'active',     -- active | paused | disabled
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trading_accounts_user ON trading_accounts(user_id);

-- Deterministic house account (matches settings.system_account_id), owned by the
-- seeded system user from migration 005.
INSERT INTO trading_accounts (id, user_id, broker, label, paper, enabled_asset_classes, status)
VALUES (
  '00000000-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-000000000001',
  'house',
  'House book',
  TRUE,
  'crypto,equity,option',
  'active'
)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- account_id on positions / orders / exit_state (backfilled to house)
-- ---------------------------------------------------------------------------

ALTER TABLE positions  ADD COLUMN IF NOT EXISTS account_id UUID;
ALTER TABLE orders     ADD COLUMN IF NOT EXISTS account_id UUID;
ALTER TABLE exit_state ADD COLUMN IF NOT EXISTS account_id UUID;

UPDATE positions SET account_id = '00000000-0000-0000-0000-000000000002' WHERE account_id IS NULL;
UPDATE orders    SET account_id = '00000000-0000-0000-0000-000000000002' WHERE account_id IS NULL;
-- exit_state inherits its position's account where possible, else house.
UPDATE exit_state es SET account_id = p.account_id
  FROM positions p
  WHERE es.position_id = p.id AND es.account_id IS NULL;
UPDATE exit_state SET account_id = '00000000-0000-0000-0000-000000000002' WHERE account_id IS NULL;

ALTER TABLE positions
  ALTER COLUMN account_id SET DEFAULT '00000000-0000-0000-0000-000000000002',
  ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE orders
  ALTER COLUMN account_id SET DEFAULT '00000000-0000-0000-0000-000000000002',
  ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE exit_state
  ALTER COLUMN account_id SET DEFAULT '00000000-0000-0000-0000-000000000002',
  ALTER COLUMN account_id SET NOT NULL;

-- FKs (idempotent — swallow duplicate on re-run).
DO $$ BEGIN
  ALTER TABLE positions ADD CONSTRAINT fk_positions_account
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE orders ADD CONSTRAINT fk_orders_account
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE exit_state ADD CONSTRAINT fk_exit_state_account
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- Account-scoped indexes + idempotency key
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_positions_account_open
  ON positions(account_id, asset_class, symbol) WHERE closed = FALSE;
CREATE INDEX IF NOT EXISTS idx_orders_account_symbol_ts
  ON orders(account_id, asset_class, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_exit_state_account
  ON exit_state(account_id);

-- Idempotency: scope the unique key to the account. Two accounts may share a
-- client_order_id string (same logical order); the broker namespaces them by
-- account once per-account creds (3.3) land.
DROP INDEX IF EXISTS uq_orders_client_order_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_account_client_order_id
  ON orders(account_id, client_order_id)
  WHERE client_order_id IS NOT NULL;
