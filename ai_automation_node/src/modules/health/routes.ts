import type { FastifyPluginAsync } from "fastify";

export const healthRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async () => {
    return {
      success: true,
      service: "ai_automation_node",
      status: "ok",
      timestamp: new Date().toISOString(),
    };
  });
};
