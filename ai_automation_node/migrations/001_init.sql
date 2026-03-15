CREATE TABLE IF NOT EXISTS customers (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  phone TEXT UNIQUE NOT NULL,
  address TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
  id SERIAL PRIMARY KEY,
  sku TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  price NUMERIC DEFAULT 0,
  stock INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
  id SERIAL PRIMARY KEY,
  customer_id INTEGER REFERENCES customers(id),
  product_id INTEGER REFERENCES products(id),
  quantity INTEGER NOT NULL,
  total_price NUMERIC NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  channel TEXT NOT NULL DEFAULT 'telegram',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_state (
  id SERIAL PRIMARY KEY,
  channel TEXT NOT NULL,
  user_id TEXT NOT NULL,
  state JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(channel, user_id)
);

CREATE TABLE IF NOT EXISTS ai_agents (
  id SERIAL PRIMARY KEY,
  tenant_slug TEXT NOT NULL,
  user_id TEXT,
  name TEXT NOT NULL,
  description TEXT,
  default_model TEXT,
  instructions TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_agents_tenant_user ON ai_agents (tenant_slug, user_id);

CREATE TABLE IF NOT EXISTS ai_agent_workflows (
  id SERIAL PRIMARY KEY,
  agent_id INTEGER NOT NULL REFERENCES ai_agents(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  graph_json JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}'::jsonb,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_agent_workflows_agent_id ON ai_agent_workflows (agent_id);

CREATE TABLE IF NOT EXISTS ai_agent_executions (
  id SERIAL PRIMARY KEY,
  workflow_id INTEGER NOT NULL REFERENCES ai_agent_workflows(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'running',
  started_at TIMESTAMP DEFAULT NOW(),
  finished_at TIMESTAMP,
  error_message TEXT,
  result_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_agent_executions_workflow ON ai_agent_executions (workflow_id, started_at DESC);

CREATE TABLE IF NOT EXISTS ai_agent_execution_logs (
  id SERIAL PRIMARY KEY,
  execution_id INTEGER NOT NULL REFERENCES ai_agent_executions(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL,
  node_type TEXT NOT NULL,
  status TEXT NOT NULL,
  input_snapshot JSONB,
  output_snapshot JSONB,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_agent_execution_logs_execution ON ai_agent_execution_logs (execution_id);

CREATE TABLE IF NOT EXISTS catalog_documents (
  id SERIAL PRIMARY KEY,
  tenant_slug TEXT NOT NULL,
  external_id TEXT NOT NULL,
  source TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding_ready BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE (tenant_slug, external_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_documents_tenant_source ON catalog_documents (tenant_slug, source);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  id SERIAL PRIMARY KEY,
  tenant_slug TEXT NOT NULL,
  user_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  idem_key TEXT NOT NULL,
  response_payload JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(tenant_slug, user_id, scope, idem_key)
);
