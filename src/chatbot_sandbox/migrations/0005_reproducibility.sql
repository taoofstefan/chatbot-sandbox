-- Reproducibility: store a redacted snapshot of the backends config and run
-- metadata (cbs version, invoking command, Python/platform) so a run can be
-- replayed and audited without the original config files. Secrets are
-- redacted in application code *before* storage (see secrets.redact_backend_config);
-- this layer never sees a plaintext key.
ALTER TABLE runs ADD COLUMN backends_json TEXT;
ALTER TABLE runs ADD COLUMN meta_json TEXT;