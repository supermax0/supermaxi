import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { query } from "../../lib/db.js";
import { getRequestContext } from "../../lib/request-context.js";

const createAgentSchema = z.object({
  name: z.string().min(1).max(150),
  description: z.string().max(2000).optional(),
  default_model: z.string().max(120).optional(),
  instructions: z.string().max(6000).optional(),
});

export const agentsRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async (request) => {
    const { tenantSlug, userId } = getRequestContext(request);
    const result = await query(
      `
        SELECT id, tenant_slug, user_id, name, description, default_model, instructions, created_at, updated_at
        FROM ai_agents
        WHERE tenant_slug = $1 AND (user_id = $2 OR user_id IS NULL)
        ORDER BY updated_at DESC
      `,
      [tenantSlug, userId],
    );
    return { success: true, agents: result.rows };
  });

  app.post("/", async (request, reply) => {
    const body = createAgentSchema.parse(request.body);
    const { tenantSlug, userId } = getRequestContext(request);

    const created = await query(
      `
        INSERT INTO ai_agents (tenant_slug, user_id, name, description, default_model, instructions)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, tenant_slug, user_id, name, description, default_model, instructions, created_at, updated_at
      `,
      [
        tenantSlug,
        userId,
        body.name.trim(),
        body.description?.trim() || null,
        body.default_model?.trim() || null,
        body.instructions?.trim() || null,
      ],
    );

    return reply.code(201).send({ success: true, agent: created.rows[0] });
  });
};
