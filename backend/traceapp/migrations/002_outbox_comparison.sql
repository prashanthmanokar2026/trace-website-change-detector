ALTER TABLE outbox ADD COLUMN before_id INTEGER;
UPDATE schema_version SET version=2;
