import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { query } from "../../lib/db.js";
import { getRequestContext } from "../../lib/request-context.js";
import { checkIdempotency, storeIdempotency, replayIdempotent } from "../../lib/idempotency.js";
import { runWorkflowById } from "./workflow-runner.js";
import { validateGraph } from "./graph-validator.js";

const IDEM_SCOPE_RUN = "workflow_run";

const graphSchema = z.object({
  nodes: z.array(z.record(z.string(), z.unknown())).default([]),
  edges: z.array(z.record(z.string(), z.unknown())).default([]),
});

const createWorkflowSchema = z.object({
  agent_id: z.number().int().positive(),
  name: z.string().min(1).max(150),
  description: z.string().max(3000).optional(),
  is_active: z.boolean().optional(),
  graph: graphSchema,
});

const updateWorkflowSchema = z.object({
  name: z.string().min(1).max(150).optional(),
  description: z.string().max(3000).optional(),
  is_active: z.boolean().optional(),
  graph: graphSchema.optional(),
});

export const workflowsRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async (request, reply) => {
    const { tenantSlug, userId } = getRequestContext(request);
    const workflowIdRaw = String((request.query as Record<string, unknown>)?.workflow_id || "").trim();

    if (workflowIdRaw) {
      const workflowId = Number(workflowIdRaw);
      if (!Number.isFinite(workflowId)) {
        return reply.code(400).send({ success: false, error: "invalid_workflow_id" });
      }
      const found = await query(
        `
          SELECT w.id, w.agent_id, w.name, w.description, w.is_active, w.graph_json AS graph, w.created_at, w.updated_at
          FROM ai_agent_workflows w
          INNER JOIN ai_agents a ON a.id = w.agent_id
          WHERE w.id = $1 AND a.tenant_slug = $2 AND (a.user_id = $3 OR a.user_id IS NULL)
          LIMIT 1
        `,
        [workflowId, tenantSlug, userId],
      );
      if (!found.rowCount) return reply.code(404).send({ success: false, error: "workflow_not_found" });
      return { success: true, workflow: found.rows[0] };
    }

    const result = await query(
      `
        SELECT w.id, w.agent_id, w.name, w.description, w.is_active, w.graph_json AS graph, w.created_at, w.updated_at
        FROM ai_agent_workflows w
        INNER JOIN ai_agents a ON a.id = w.agent_id
        WHERE a.tenant_slug = $1 AND (a.user_id = $2 OR a.user_id IS NULL)
        ORDER BY w.updated_at DESC
      `,
      [tenantSlug, userId],
    );
    return { success: true, workflows: result.rows };
  });

  app.post("/", async (request, reply) => {
    const body = createWorkflowSchema.parse(request.body);
    const { tenantSlug, userId } = getRequestContext(request);

    const nodes = (body.graph.nodes || []) as { id: string; type?: string; data?: Record<string, unknown>; position?: { x: number; y: number } }[];
    const edges = (body.graph.edges || []) as { id?: string; source: string; target: string; on?: string }[];
    const validation = validateGraph(nodes, edges);
    if (!validation.valid) {
      return reply.code(400).send({
        success: false,
        error: "validation_failed",
        validation_errors: validation.errors,
      });
    }

    const agent = await query(
      `
        SELECT id
        FROM ai_agents
        WHERE id = $1 AND tenant_slug = $2 AND (user_id = $3 OR user_id IS NULL)
        LIMIT 1
      `,
      [body.agent_id, tenantSlug, userId],
    );
    if (!agent.rowCount) return reply.code(404).send({ success: false, error: "agent_not_found" });

    const created = await query(
      `
        INSERT INTO ai_agent_workflows (agent_id, name, description, is_active, graph_json)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, agent_id, name, description, is_active, graph_json AS graph, created_at, updated_at
      `,
      [
        body.agent_id,
        body.name.trim(),
        body.description?.trim() || null,
        body.is_active ?? true,
        JSON.stringify(body.graph),
      ],
    );
    return reply.code(201).send({ success: true, workflow: created.rows[0] });
  });

  app.put("/:workflowId", async (request, reply) => {
    const workflowId = Number((request.params as Record<string, unknown>).workflowId);
    if (!Number.isFinite(workflowId)) {
      return reply.code(400).send({ success: false, error: "invalid_workflow_id" });
    }
    const body = updateWorkflowSchema.parse(request.body);
    const { tenantSlug, userId } = getRequestContext(request);

    const exists = await query(
      `
        SELECT w.id
        FROM ai_agent_workflows w
        INNER JOIN ai_agents a ON a.id = w.agent_id
        WHERE w.id = $1 AND a.tenant_slug = $2 AND (a.user_id = $3 OR a.user_id IS NULL)
      `,
      [workflowId, tenantSlug, userId],
    );
    if (!exists.rowCount) return reply.code(404).send({ success: false, error: "workflow_not_found" });

    if (body.graph) {
      const nodes = (body.graph.nodes || []) as { id: string; type?: string; data?: Record<string, unknown>; position?: { x: number; y: number } }[];
      const edges = (body.graph.edges || []) as { id?: string; source: string; target: string; on?: string }[];
      const validation = validateGraph(nodes, edges);
      if (!validation.valid) {
        return reply.code(400).send({
          success: false,
          error: "validation_failed",
          validation_errors: validation.errors,
        });
      }
    }

    const updated = await query(
      `
        UPDATE ai_agent_workflows
        SET
          name = COALESCE($2, name),
          description = COALESCE($3, description),
          is_active = COALESCE($4, is_active),
          graph_json = COALESCE($5, graph_json),
          updated_at = NOW()
        WHERE id = $1
        RETURNING id, agent_id, name, description, is_active, graph_json AS graph, created_at, updated_at
      `,
      [
        workflowId,
        body.name?.trim() || null,
        body.description?.trim() || null,
        body.is_active ?? null,
        body.graph ? JSON.stringify(body.graph) : null,
      ],
    );

    return { success: true, workflow: updated.rows[0] };
  });

  app.post("/:workflowId/run", async (request, reply) => {
    const workflowId = Number((request.params as Record<string, unknown>).workflowId);
    if (!Number.isFinite(workflowId)) {
      return reply.code(400).send({ success: false, error: "invalid_workflow_id" });
    }
    const { tenantSlug, userId } = getRequestContext(request);
    const body = (request.body as Record<string, unknown>) || {};
    const idemKey = (request.headers["idempotency-key"] ?? "").toString().trim();

    if (idemKey) {
      const idem = await checkIdempotency(request, IDEM_SCOPE_RUN);
      if (idem.alreadyProcessed && idem.responsePayload != null) {
        return replayIdempotent(reply, idem.responsePayload);
      }
    }

    const workflowExists = await query(
      `
        SELECT w.id
        FROM ai_agent_workflows w
        INNER JOIN ai_agents a ON a.id = w.agent_id
        WHERE w.id = $1 AND a.tenant_slug = $2 AND (a.user_id = $3 OR a.user_id IS NULL)
      `,
      [workflowId, tenantSlug, userId],
    );
    if (!workflowExists.rowCount) {
      return reply.code(404).send({ success: false, error: "workflow_not_found" });
    }

    const requestId = (request as { id?: string }).id ?? null;
    const inserted = await query<{ id: number }>(
      `INSERT INTO ai_agent_executions (workflow_id, status, request_id) VALUES ($1, 'queued', $2) RETURNING id`,
      [workflowId, requestId],
    );
    const executionId = inserted.rows[0].id;
    const queuedPayload = {
      success: true,
      execution: { executionId, status: "queued" as const },
    };

    if (idemKey) {
      await storeIdempotency(request, IDEM_SCOPE_RUN, queuedPayload);
    }

    setImmediate(() => {
      runWorkflowById(workflowId, tenantSlug, userId, body, { executionId }).catch((err) => {
        request.log?.error?.({ err, workflowId, executionId }, "Workflow run failed");
      });
    });

    return reply.code(202).send(queuedPayload);
  });

  app.get("/:workflowId/executions", async (request, reply) => {
    const workflowId = Number((request.params as Record<string, unknown>).workflowId);
    if (!Number.isFinite(workflowId)) {
      return reply.code(400).send({ success: false, error: "invalid_workflow_id" });
    }
    const { tenantSlug, userId } = getRequestContext(request);
    const limit = Math.min(Number((request.query as { limit?: string }).limit) || 50, 100);

    const rows = await query(
      `
        SELECT e.id, e.workflow_id, e.status, e.started_at, e.finished_at, e.error_message, e.result_summary, e.request_id
        FROM ai_agent_executions e
        INNER JOIN ai_agent_workflows w ON w.id = e.workflow_id
        INNER JOIN ai_agents a ON a.id = w.agent_id
        WHERE w.id = $1 AND a.tenant_slug = $2 AND (a.user_id = $3 OR a.user_id IS NULL)
        ORDER BY e.started_at DESC
        LIMIT $4
      `,
      [workflowId, tenantSlug, userId, limit],
    );
    return { success: true, executions: rows.rows };
  });

  app.get("/:workflowId/executions/:executionId/logs", async (request, reply) => {
    const workflowId = Number((request.params as Record<string, unknown>).workflowId);
    const executionId = Number((request.params as Record<string, unknown>).executionId);
    if (!Number.isFinite(workflowId) || !Number.isFinite(executionId)) {
      return reply.code(400).send({ success: false, error: "invalid_workflow_id_or_execution_id" });
    }
    const { tenantSlug, userId } = getRequestContext(request);

    const exec = await query(
      `
        SELECT e.id
        FROM ai_agent_executions e
        INNER JOIN ai_agent_workflows w ON w.id = e.workflow_id
        INNER JOIN ai_agents a ON a.id = w.agent_id
        WHERE e.id = $1 AND w.id = $2 AND a.tenant_slug = $3 AND (a.user_id = $4 OR a.user_id IS NULL)
      `,
      [executionId, workflowId, tenantSlug, userId],
    );
    if (!exec.rowCount) {
      return reply.code(404).send({ success: false, error: "execution_not_found" });
    }

    const logs = await query(
      `
        SELECT id, execution_id, node_id, node_type, status, input_snapshot, output_snapshot, error_message, duration_ms, attempt_no, error_code, created_at
        FROM ai_agent_execution_logs
        WHERE execution_id = $1
        ORDER BY created_at ASC
      `,
      [executionId],
    );
    return { success: true, logs: logs.rows };
  });

  app.post("/:workflowId/executions/:executionId/retry", async (request, reply) => {
    const workflowId = Number((request.params as Record<string, unknown>).workflowId);
    const executionId = Number((request.params as Record<string, unknown>).executionId);
    if (!Number.isFinite(workflowId) || !Number.isFinite(executionId)) {
      return reply.code(400).send({ success: false, error: "invalid_workflow_id_or_execution_id" });
    }
    const { tenantSlug, userId } = getRequestContext(request);
    const body = (request.body as Record<string, unknown>) || {};

    const exec = await query<{ id: number }>(
      `
        SELECT e.id
        FROM ai_agent_executions e
        INNER JOIN ai_agent_workflows w ON w.id = e.workflow_id
        INNER JOIN ai_agents a ON a.id = w.agent_id
        WHERE e.id = $1 AND w.id = $2 AND a.tenant_slug = $3 AND (a.user_id = $4 OR a.user_id IS NULL)
      `,
      [executionId, workflowId, tenantSlug, userId],
    );
    if (!exec.rowCount) {
      return reply.code(404).send({ success: false, error: "execution_not_found" });
    }

    const inserted = await query<{ id: number }>(
      `INSERT INTO ai_agent_executions (workflow_id, status) VALUES ($1, 'queued') RETURNING id`,
      [workflowId],
    );
    const newExecutionId = inserted.rows[0].id;
    setImmediate(() => {
      runWorkflowById(workflowId, tenantSlug, userId, body, { executionId: newExecutionId }).catch((err) => {
        request.log?.error?.({ err, workflowId, executionId: newExecutionId }, "Workflow retry run failed");
      });
    });
    return reply.code(202).send({
      success: true,
      execution: { executionId: newExecutionId, status: "queued" as const },
    });
  });
};
