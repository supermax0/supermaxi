# AI Automation Node (Phase 2)

Standalone Node.js + TypeScript backend for a mini-n8n style workflow engine, designed to coexist with the current Flask system without breaking it.

## What Is Included

- Fastify backend (`/api/agents`, `/api/workflows`, `/api/webhooks`, `/api/orders`, `/api/customers`, `/api/catalog`).
- Workflow runner with basic node execution:
  - `start`, `router_agent`, `ai_extractor`, `knowledge_agent`, `sales_agent`,
  - `condition`, `sql_save_order`, `telegram_reply`, `end`.
- OpenAI wrapper for chat + embeddings.
- Qdrant upsert support for catalog embedding ingestion.
- PostgreSQL migration SQL + migration runner.
- Dockerfile + Docker Compose (`postgres`, `qdrant`, `backend`).
- Basic Kubernetes manifests.
- Basic tests (unit + route).
- OpenAPI starter file.

## Project Tree

```text
ai_automation_node/
  src/
    app.ts
    index.ts
    config/env.ts
    lib/
      db.ts
      idempotency.ts
      request-context.ts
    modules/
      ai/openai.service.ts
      agents/routes.ts
      catalog/routes.ts
      catalog/qdrant.service.ts
      customers/routes.ts
      health/routes.ts
      orders/routes.ts
      webhooks/telegram.routes.ts
      workflows/routes.ts
      workflows/workflow-runner.ts
      workflows/expression.ts
    prompts/agent-templates.ts
  migrations/001_init.sql
  scripts/run-migrations.ts
  workflows/telegram-sales-flow.json
  openapi/openapi.yaml
  tests/
    expression.test.ts
    health.test.ts
  Dockerfile
  docker-compose.yml
  .env.example
```

## Quick Start (Local)

```bash
cd ai_automation_node
cp .env.example .env
npm ci
npm run migrate
npm run dev
```

API will run on `http://localhost:4000`.

## One Command Run (Docker Compose)

```bash
cd ai_automation_node
cp .env.example .env
docker compose up --build
```

## Deployment on a server

- **DATABASE_URL**: On the server, set `DATABASE_URL` in `.env` to match your real PostgreSQL (user, password, host, port, dbname). The error `password authentication failed for user "postgres"` means the URL does not match the DB server credentials.
- **Start without failing on migration**: To let the app start even if migration fails (e.g. wrong DB URL or DB not ready), use:
  - Docker: the Compose command runs `npm run migrate || true && npm run start`.
  - Manual: `npm run start:with-migrate` (runs migrate then start; migration failure does not stop the server).

## Sample Endpoints

- `GET /health`
- `GET/POST /api/agents`
- `GET/POST /api/workflows`
- `PUT /api/workflows/:workflowId`
- `POST /api/workflows/:workflowId/run`
- `POST /api/webhooks/telegram/:workflowId`
- `GET/POST /api/customers`
- `GET/POST /api/orders`
- `POST /api/catalog/ingest`

## Security Notes

- API keys are read only from env vars (`OPENAI_API_KEY`, `QDRANT_API_KEY`, `TELEGRAM_BOT_TOKEN`).
- Basic global rate limiting enabled.
- Idempotency support on critical write endpoints via `Idempotency-Key`.
- Input validation uses `zod`.

## Next Steps

1. Add full auth layer (JWT/session validation against your tenant system).
2. Add queue-based execution (BullMQ/Redis) for long-running workflows.
3. Add richer condition engine and branching UI support.
4. Expand integration adapters (Facebook/WhatsApp/Messenger).
5. Add production-grade observability (structured logs + metrics + tracing).
