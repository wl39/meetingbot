ALTER TABLE upload_sessions ADD COLUMN owner TEXT;
UPDATE schema_version SET version=7;
