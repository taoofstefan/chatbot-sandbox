-- 0003: per-result validation report index.
-- The validation_json column was added directly to 0001's CREATE TABLE for
-- new databases. The Python migration runner ALTERs it onto existing v1/v2
-- databases (with a guard so legacy DBs without a results table are skipped).
-- This file is therefore a no-op on most databases; it just ensures the
-- composite index exists for fast per-prompt lookups.
CREATE INDEX IF NOT EXISTS idx_results_validation ON results(run_id, prompt_id);
