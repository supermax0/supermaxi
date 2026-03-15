import Fastify from "fastify";
import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import rateLimit from "@fastify/rate-limit";
import multipart from "@fastify/multipart";
import { ZodError } from "zod";
import { env } from "./config/env.js";
import { healthRoutes } from "./modules/health/routes.js";
import { agentsRoutes } from "./modules/agents/routes.js";
import { workflowsRoutes } from "./modules/workflows/routes.js";
import { customersRoutes } from "./modules/customers/routes.js";
import { ordersRoutes } from "./modules/orders/routes.js";
import { catalogRoutes } from "./modules/catalog/routes.js";
import { telegramWebhookRoutes } from "./modules/webhooks/telegram.routes.js";

export function buildApp() {
  const app = Fastify({
    logger: true,
    trustProxy: true,
    requestIdHeader: "x-request-id",
  });

  app.register(cors, { origin: true, credentials: true });
  app.register(helmet);
  app.register(multipart, { limits: { fileSize: 20 * 1024 * 1024 } });
  app.register(rateLimit, {
    global: true,
    max: env.RATE_LIMIT_MAX,
    timeWindow: env.RATE_LIMIT_WINDOW_MS,
  });

  app.get("/", async () => ({
    success: true,
    service: "ai_automation_node",
    docs: "/openapi",
  }));

  app.register(healthRoutes, { prefix: "/health" });
  app.register(agentsRoutes, { prefix: "/api/agents" });
  app.register(workflowsRoutes, { prefix: "/api/workflows" });
  app.register(customersRoutes, { prefix: "/api/customers" });
  app.register(ordersRoutes, { prefix: "/api/orders" });
  app.register(catalogRoutes, { prefix: "/api/catalog" });
  app.register(telegramWebhookRoutes, { prefix: "/api/webhooks" });

  app.setErrorHandler((error, request, reply) => {
    request.log.error(error);
    const message = error instanceof Error ? error.message : "Unknown error";

    if (error instanceof ZodError) {
      return reply.code(400).send({
        success: false,
        error: "validation_error",
        details: error.issues,
      });
    }
    return reply.code(500).send({
      success: false,
      error: "internal_server_error",
      message: env.NODE_ENV === "production" ? "Internal server error" : message,
    });
  });

  return app;
}
