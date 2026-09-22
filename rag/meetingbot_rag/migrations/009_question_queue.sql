ALTER TABLE query_runs ADD COLUMN input TEXT;
ALTER TABLE query_runs ADD COLUMN idempotency_key TEXT;
ALTER TABLE query_runs ADD COLUMN available_at REAL NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX question_idempotency ON query_runs(subject,workspace_id,idempotency_key)
 WHERE idempotency_key IS NOT NULL;
CREATE INDEX question_queue ON query_runs(created_at,id)
 WHERE input IS NOT NULL AND json_extract(result,'$.status')='queued';
UPDATE schema_version SET version=9;
