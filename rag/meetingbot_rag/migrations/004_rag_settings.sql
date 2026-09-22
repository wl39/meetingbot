CREATE TABLE rag_settings(
 id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
 body TEXT NOT NULL, updated_at REAL NOT NULL);
UPDATE schema_version SET version=4;
