import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { query } from "../../lib/db.js";
import { getRequestContext } from "../../lib/request-context.js";
import { createEmbedding } from "../ai/openai.service.js";
import { ensureCollection, upsertVectorPoint } from "./qdrant.service.js";

const ingestSchema = z.object({
  source: z.string().max(120).default("manual"),
  rows: z.array(
    z.object({
      id: z.string().min(1).max(120),
      text: z.string().min(1),
      metadata: z.record(z.string(), z.unknown()).optional(),
    }),
  ),
});

export const catalogRoutes: FastifyPluginAsync = async (app) => {
  app.post("/ingest", async (request, reply) => {
    const body = ingestSchema.parse(request.body);
    const { tenantSlug } = getRequestContext(request);

    await ensureCollection();
    const results: Array<{ id: string; embedded: boolean }> = [];

    for (const row of body.rows) {
      const text = row.text.trim();
      const embedding = await createEmbedding(text);

      await query(
        `
          INSERT INTO catalog_documents (tenant_slug, external_id, source, content, metadata, embedding_ready)
          VALUES ($1, $2, $3, $4, $5, $6)
          ON CONFLICT (tenant_slug, external_id) DO UPDATE SET
            source = EXCLUDED.source,
            content = EXCLUDED.content,
            metadata = EXCLUDED.metadata,
            embedding_ready = EXCLUDED.embedding_ready,
            updated_at = NOW()
        `,
        [tenantSlug, row.id, body.source, text, JSON.stringify(row.metadata || {}), Boolean(embedding)],
      );

      if (embedding) {
        await upsertVectorPoint(`${tenantSlug}-${row.id}`, embedding, {
          tenant_slug: tenantSlug,
          external_id: row.id,
          source: body.source,
          content: text,
          ...row.metadata,
        });
      }

      results.push({ id: row.id, embedded: Boolean(embedding) });
    }

    return reply.code(202).send({
      success: true,
      message: "Catalog ingestion accepted",
      items: results,
    });
  });
};
