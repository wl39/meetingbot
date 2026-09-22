CREATE TABLE workspace_guides(
 workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
 version INTEGER NOT NULL CHECK(version > 0),
 content TEXT NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 content_hash TEXT NOT NULL,
 updated_at REAL NOT NULL
);
UPDATE schema_version SET version=5;
