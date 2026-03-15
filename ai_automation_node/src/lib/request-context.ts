import type { FastifyRequest } from "fastify";

export interface RequestContext {
  tenantSlug: string;
  userId: string;
}

export function getRequestContext(request: FastifyRequest): RequestContext {
  const tenantHeader = request.headers["x-tenant-slug"];
  const userHeader = request.headers["x-user-id"];

  const tenantSlug = (Array.isArray(tenantHeader) ? tenantHeader[0] : tenantHeader || "default").toString().trim();
  const userId = (Array.isArray(userHeader) ? userHeader[0] : userHeader || "system").toString().trim();

  return {
    tenantSlug: tenantSlug || "default",
    userId: userId || "system",
  };
}
