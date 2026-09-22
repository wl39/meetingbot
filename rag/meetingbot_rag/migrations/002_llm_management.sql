CREATE TABLE IF NOT EXISTS llm_settings (
 id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER NOT NULL,
 body TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_model_catalog (
 connection_id TEXT PRIMARY KEY, models TEXT NOT NULL, fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_model_checks (
 provider_id TEXT PRIMARY KEY, result TEXT NOT NULL, checked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS prompt_versions (
 id TEXT PRIMARY KEY, sequence INTEGER UNIQUE NOT NULL, name TEXT NOT NULL,
 content TEXT NOT NULL, content_hash TEXT NOT NULL, note TEXT NOT NULL,
 created_at REAL NOT NULL, restored_from_id TEXT
);
CREATE TABLE IF NOT EXISTS prompt_settings (
 id INTEGER PRIMARY KEY CHECK (id=1), active_version_id TEXT NOT NULL REFERENCES prompt_versions(id)
);
UPDATE schema_version SET version=2;
