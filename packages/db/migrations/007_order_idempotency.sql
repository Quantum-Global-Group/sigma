-- 007_order_idempotency.sql
--
-- Hardens the orders table for the OrderIntent execution model:
--   * client_order_id — deterministic idempotency key. UNIQUE so a retried
--     worker tick can't double-place the same logical order. This is the
--     safety guard for live trading (esp. Alpaca equities).
--   * order_type / time_in_force / limit_px / stop_px — richer order spec
--     carried from OrderIntent into the persisted record.

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(64),
  ADD COLUMN IF NOT EXISTS order_type      VARCHAR(16) NOT NULL DEFAULT 'market',
  ADD COLUMN IF NOT EXISTS time_in_force   VARCHAR(8)  NOT NULL DEFAULT 'day',
  ADD COLUMN IF NOT EXISTS limit_px        NUMERIC(20,8),
  ADD COLUMN IF NOT EXISTS stop_px         NUMERIC(20,8);

-- Idempotency: at most one order per client_order_id. Partial unique index so
-- legacy rows with NULL client_order_id (pre-007) don't collide.
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_client_order_id
  ON orders(client_order_id)
  WHERE client_order_id IS NOT NULL;
