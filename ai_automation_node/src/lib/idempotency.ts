import type { FastifyReply, FastifyRequest } from "fastify";
import { query } from "./db.js";
import { getRequestContext } from "./request-context.js";

export interface IdempotencyResult {
  alreadyProcessed: boolean;
  responsePayload?: unknown;
}

export async function checkIdempotency(request: FastifyRequest, scope: string): Promise<IdempotencyResult> {
  const key = (request.headers["idempotency-key"] || "").toString().trim();
  if (!key) {
    return { alreadyProcessed: false };
  }

  const { tenantSlug, userId } = getRequestContext(request);
  const found = await query<{ response_payload: unknown }>(
    `
      SELECT response_payload
      FROM idempotency_keys
      WHERE tenant_slug = $1 AND user_id = $2 AND scope = $3 AND idem_key = $4
      LIMIT 1
    `,
    [tenantSlug, userId, scope, key],
  );

  if (found.rowCount) {
    return { alreadyProcessed: true, responsePayload: found.rows[0].response_payload };
  }
  return { alreadyProcessed: false };
}

export async function storeIdempotency(
  request: FastifyRequest,
  scope: string,
  payload: unknown,
): Promise<void> {
  const key = (request.headers["idempotency-key"] || "").toString().trim();
  if (!key) return;

  const { tenantSlug, userId } = getRequestContext(request);
  await query(
    `
      INSERT INTO idempotency_keys (tenant_slug, user_id, scope, idem_key, response_payload)
      VALUES ($1, $2, $3, $4, $5)
      ON CONFLICT (tenant_slug, user_id, scope, idem_key) DO NOTHING
    `,
    [tenantSlug, userId, scope, JSON.stringify(payload)],
  );
}

export function replayIdempotent(reply: FastifyReply, payload: unknown) {
  return reply.code(200).send({
    success: true,
    idempotent_replay: true,
    ...(typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>) : { data: payload }),
  });
}
