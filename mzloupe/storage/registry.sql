-- Durable project definitions remain available when derived caches are cleared.
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    configuration TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    opened_at TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    source_path TEXT,
    error TEXT NOT NULL DEFAULT ''
);

-- Remember imported manifest locations independently of their portable UUIDs.
CREATE TABLE IF NOT EXISTS project_sources (
    path TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE
);
