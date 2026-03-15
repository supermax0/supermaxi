import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { checkIdempotency, replayIdempotent, storeIdempotency } from "../../lib/idempotency.js";
import { query } from "../../lib/db.js";

const createCustomerSchema = z.object({
  name: z.string().min(1).max(200),
  phone: z.string().min(3).max(50),
  address: z.string().max(400).optional(),
});

export const customersRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async () => {
    const result = await query(
      `
        SELECT id, name, phone, address, created_at
        FROM customers
        ORDER BY created_at DESC
        LIMIT 100
      `,
    );
    return { success: true, customers: result.rows };
  });

  app.post("/", async (request, reply) => {
    const maybeReplay = await checkIdempotency(request, "customers.create");
    if (maybeReplay.alreadyProcessed) return replayIdempotent(reply, maybeReplay.responsePayload);

    const body = createCustomerSchema.parse(request.body);
    const created = await query(
      `
        INSERT INTO customers (name, phone, address)
        VALUES ($1, $2, $3)
        ON CONFLICT (phone) DO UPDATE SET
          name = EXCLUDED.name,
          address = EXCLUDED.address
        RETURNING id, name, phone, address, created_at
      `,
      [body.name.trim(), body.phone.trim(), body.address?.trim() || null],
    );

    const payload = { customer: created.rows[0] };
    await storeIdempotency(request, "customers.create", payload);
    return reply.code(201).send({ success: true, ...payload });
  });
};
