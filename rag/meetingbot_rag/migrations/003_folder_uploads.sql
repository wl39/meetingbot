CREATE TABLE upload_sessions(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, folder_name TEXT NOT NULL,
 description TEXT NOT NULL, files TEXT NOT NULL, total_bytes INTEGER NOT NULL,
 state TEXT NOT NULL, expires_at REAL NOT NULL, workspace_id TEXT UNIQUE);
UPDATE schema_version SET version=3;
