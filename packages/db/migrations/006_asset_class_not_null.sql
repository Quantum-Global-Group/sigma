-- 006_asset_class_not_null.sql
--
-- Run AFTER migration 005 has been live long enough that every signal_history
-- and signal_cache row has a non-null asset_class (the 005 backfill handles
-- pre-existing rows; 006 protects against future inserts that forget the
-- column).

-- Sanity check: refuse to apply if any nulls remain.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM signal_history WHERE asset_class IS NULL) THEN
    RAISE EXCEPTION 'signal_history has rows with NULL asset_class — backfill before applying 006';
  END IF;
END $$;

ALTER TABLE signal_history
  ALTER COLUMN asset_class SET DEFAULT 'equity',
  ALTER COLUMN asset_class SET NOT NULL;

-- signal_cache.asset_class is already NOT NULL (set in 005 as part of the PK
-- widening) — this is a no-op safety net.
ALTER TABLE signal_cache
  ALTER COLUMN asset_class SET NOT NULL;
