CREATE TABLE meeting_policies(
 workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, body TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE meeting_subscriptions(
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL, owner TEXT NOT NULL, enabled INTEGER NOT NULL,
 revision_id TEXT, version INTEGER NOT NULL, updated_at REAL NOT NULL, source_generation INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(workspace_id,session_id));
CREATE TABLE meeting_jobs(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL, owner TEXT NOT NULL, utterance_id TEXT NOT NULL,
 utterance_revision INTEGER NOT NULL, source_key TEXT NOT NULL, text TEXT NOT NULL,
 input TEXT NOT NULL, origin TEXT NOT NULL, score INTEGER, classification TEXT,
 queue_class TEXT, state TEXT NOT NULL, stage TEXT NOT NULL,
 received_at REAL NOT NULL, deadline_at REAL NOT NULL, deadline_missed INTEGER NOT NULL DEFAULT 0,
 policy_version INTEGER NOT NULL, policy TEXT NOT NULL, provider_id TEXT NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, available_at REAL NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, checkpoint TEXT, result TEXT, reason TEXT,
 UNIQUE(workspace_id,session_id,source_key,policy_version));
CREATE INDEX meeting_schedule ON meeting_jobs(state,available_at,queue_class,deadline_at);
CREATE INDEX meeting_session_jobs ON meeting_jobs(workspace_id,session_id,owner,created_at);
UPDATE schema_version SET version=6;
