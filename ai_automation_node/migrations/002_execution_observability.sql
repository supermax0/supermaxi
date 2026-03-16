-- Observability: request correlation and node-level metadata for executions and logs

ALTER TABLE ai_agent_executions
  ADD COLUMN IF NOT EXISTS request_id TEXT;

CREATE INDEX IF NOT EXISTS idx_ai_agent_executions_request_id
  ON ai_agent_executions (request_id) WHERE request_id IS NOT NULL;

ALTER TABLE ai_agent_execution_logs
  ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
  ADD COLUMN IF NOT EXISTS attempt_no INTEGER DEFAULT 1,
  ADD COLUMN IF NOT EXISTS error_code TEXT;

CREATE INDEX IF NOT EXISTS idx_ai_agent_execution_logs_execution_created
  ON ai_agent_execution_logs (execution_id, created_at);
