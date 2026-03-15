import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { query } from "../../lib/db.js";
import { getRequestContext } from "../../lib/request-context.js";
import { runWorkflowById } from "./workflow-runner.js";

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

    const result = await runWorkflowById(
      workflowId,
      tenantSlug,
      userId,
      (request.body as Record<string, unknown>) || {},
    );
    return reply.code(202).send({ success: true, execution: result });
  });
};
