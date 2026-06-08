CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    prompt_set_name TEXT,
    backend_names TEXT NOT NULL,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL,
    backend_name TEXT NOT NULL,
    model TEXT,
    output TEXT,
    error TEXT,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    started_at TEXT NOT NULL,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_prompt ON results(prompt_id);
CREATE INDEX IF NOT EXISTS idx_results_backend ON results(backend_name);

CREATE TABLE IF NOT EXISTS tags (
    result_id INTEGER NOT NULL REFERENCES results(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (result_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
