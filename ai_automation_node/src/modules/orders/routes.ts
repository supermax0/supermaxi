import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { checkIdempotency, replayIdempotent, storeIdempotency } from "../../lib/idempotency.js";
import { query } from "../../lib/db.js";

const createOrderSchema = z.object({
  customer_id: z.number().int().positive(),
  product_id: z.number().int().positive(),
  quantity: z.number().int().positive(),
  total_price: z.number().nonnegative(),
  channel: z.string().max(40).default("telegram"),
  status: z.string().max(30).default("pending"),
});

export const ordersRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async () => {
    const result = await query(
      `
        SELECT o.id, o.customer_id, o.product_id, o.quantity, o.total_price, o.status, o.channel, o.created_at,
               c.name AS customer_name, c.phone AS customer_phone,
               p.name AS product_name
        FROM orders o
        LEFT JOIN customers c ON c.id = o.customer_id
        LEFT JOIN products p ON p.id = o.product_id
        ORDER BY o.created_at DESC
        LIMIT 200
      `,
    );
    return { success: true, orders: result.rows };
  });

  app.post("/", async (request, reply) => {
    const maybeReplay = await checkIdempotency(request, "orders.create");
    if (maybeReplay.alreadyProcessed) return replayIdempotent(reply, maybeReplay.responsePayload);

    const body = createOrderSchema.parse(request.body);
    const created = await query(
      `
        INSERT INTO orders (customer_id, product_id, quantity, total_price, status, channel)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, customer_id, product_id, quantity, total_price, status, channel, created_at
      `,
      [body.customer_id, body.product_id, body.quantity, body.total_price, body.status, body.channel],
    );

    const payload = { order: created.rows[0] };
    await storeIdempotency(request, "orders.create", payload);
    return reply.code(201).send({ success: true, ...payload });
  });
};
