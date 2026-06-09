-- 0004: agentic-run persistence.
-- These tables hold the audit trail for one (case, model) agentic run:
--   agent_runs:    one row per agent run (per result row in `results`)
--   tool_calls:    one row per tool call the agent made
--   judge_scores:  one row per (judge-model, rubric) pair
-- The grade report (auto + judge) is stored in the existing
-- `results.validation_json` column for backward compatibility with the
-- single-turn dashboard; the structured tables here power the new
-- agentic dashboard route.

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL,
    backend_name TEXT NOT NULL,
    final_answer TEXT,
    total_steps INTEGER NOT NULL DEFAULT 0,
    completed_normally INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    final_messages_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_run ON agent_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_prompt ON agent_runs(run_id, prompt_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_backend ON agent_runs(backend_name);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_run_id INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_agent_run ON tool_calls(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_step ON tool_calls(agent_run_id, step_index);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name);

CREATE TABLE IF NOT EXISTS judge_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_run_id INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    rubric TEXT NOT NULL,
    judge_backend TEXT NOT NULL,
    judge_model TEXT,
    score INTEGER NOT NULL,
    evidence TEXT,
    raw_response TEXT,
    latency_ms INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_judge_scores_agent_run ON judge_scores(agent_run_id);
CREATE INDEX IF NOT EXISTS idx_judge_scores_rubric ON judge_scores(rubric);
