import { z } from "zod";
import { finoraCall, settle } from "./transport";
import type { FinoraRequest } from "@shared/ipc";
import { desktopBridge, hasDesktopBridge } from "@/services/bridge";
import { FinoraApiError } from "./errors";
import { useSession } from "@/stores/session";
import {
  auditLocationSchema,
  auditSessionSchema,
  auditLineSchema,
  commandSchema,
  linePageSchema,
  investigationSchema,
  historySchema,
  movementSchema,
  preparedAuditSchema,
  auditLocalSchema,
  auditReceiptSchema,
  auditContext,
  type AuditCommand,
} from "@shared/inventoryAudit";
export * from "@shared/inventoryAudit";
const base = "/api/v1/desktop/inventory-audits";
const envelope = <T extends z.ZodTypeAny>(schema: T) => z.object({ success: z.literal(true), data: schema });
async function auditCall<T>(request: FinoraRequest, schema: z.ZodType<T, z.ZodTypeDef, unknown>): Promise<T> {
  if (
    request.method === "POST" &&
    (request.path === base || /^\/api\/v1\/desktop\/inventory-audits\/\d+\/commands$/.test(request.path))
  ) {
    const session = useSession.getState().session;
    if (!session) throw new FinoraApiError("unauthenticated");
    const body = request.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new FinoraApiError("validation");
    request = { ...request, body: { ...body, audit_context: auditContext(session) } };
  }
  if (hasDesktopBridge()) return finoraCall(request, schema);
  const url = new URL(request.path, window.location.origin);
  for (const [key, value] of Object.entries(request.query ?? {}))
    if (value !== undefined) url.searchParams.set(key, String(value));
  let response: Response;
  try {
    response = await fetch(url, {
      method: request.method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...(request.body ? { body: JSON.stringify(request.body) } : {}),
    });
  } catch {
    throw new FinoraApiError("network");
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new FinoraApiError("invalid_response");
  }
  return settle(
    request.path,
    response.ok
      ? { ok: true, status: response.status, data }
      : { ok: false, failure: "http", status: response.status, data },
    schema,
  );
}
export const inventoryAudit = {
  async openWebsite(sessionId?: number) {
    if (sessionId !== undefined && (!Number.isSafeInteger(sessionId) || sessionId <= 0))
      throw new FinoraApiError("validation");
    const path = `/inventory/smart-audit${sessionId ? `?session=${sessionId}` : ""}`;
    if (hasDesktopBridge()) return desktopBridge().app.openInFinora(path);
    window.open(path, "_blank", "noopener");
  },
  async openSource(
    kind: "product" | "purchase" | "invoice" | "branch_transfer" | "warehouse_transfer",
    id: number,
  ) {
    if (!Number.isSafeInteger(id) || id <= 0) throw new FinoraApiError("validation");
    const paths = {
      product: `/inventory/report/${id}`,
      purchase: `/purchases/edit/${id}`,
      invoice: `/orders/${id}`,
      branch_transfer: `/inventory/transfers/${id}`,
      warehouse_transfer: "/wholesale/transfers",
    };
    if (hasDesktopBridge()) return desktopBridge().app.openInFinora(paths[kind]);
    window.open(paths[kind], "_blank", "noopener");
  },
  async localStatus() {
    if (!hasDesktopBridge()) return { available: false, offline: false, prepared_records: 0, items: [] };
    return (await auditCall({ method: "GET", path: `${base}/local/status` }, envelope(auditLocalSchema)))
      .data;
  },
  async retryLocal(key: string) {
    return (
      await auditCall(
        { method: "POST", path: `${base}/local/actions`, body: { operation: "retry", key } },
        envelope(commandSchema),
      )
    ).data;
  },
  async discardLocal(key: string, reason: string) {
    return (
      await auditCall(
        { method: "POST", path: `${base}/local/actions`, body: { operation: "discard", key, reason } },
        envelope(z.object({ discarded: z.literal(true) })),
      )
    ).data;
  },
  async prepareOffline(id: number, line_ids: number[]) {
    return (
      await auditCall(
        {
          method: "POST",
          path: `${base}/${id}/commands`,
          body: { action: "prepare_offline", line_ids, idempotency_key: crypto.randomUUID() },
        },
        envelope(preparedAuditSchema),
      )
    ).data;
  },
  async export(id: number, format: "print" | "pdf" | "xlsx") {
    if (hasDesktopBridge())
      return desktopBridge().reports.export({
        section: "inventory_audit",
        format,
        title: `جرد المخزون ${id}`,
        query: { period: "today", audit_id: id },
      });
    window.open(`${base}/${id}/${format === "xlsx" ? "xlsx" : "print"}`, "_blank", "noopener");
    return { saved: false };
  },
  async meta() {
    return (
      await auditCall(
        { method: "GET", path: `${base}/meta` },
        envelope(
          z.object({
            locations: z.object({
              branch: z.array(auditLocationSchema),
              warehouse: z.array(auditLocationSchema),
            }),
            permissions: z.array(z.string()),
            capabilities: z.record(z.boolean()),
          }),
        ),
      )
    ).data;
  },
  async sessions(page = 1, status = "", page_size = 25) {
    return (
      await auditCall(
        { method: "GET", path: base, query: { page, status, page_size } },
        envelope(
          z.object({
            items: z.array(auditSessionSchema),
            page: z.number(),
            page_size: z.number(),
            total: z.number(),
            total_pages: z.number(),
          }),
        ),
      )
    ).data;
  },
  async get(id: number) {
    return (await auditCall({ method: "GET", path: `${base}/${id}` }, envelope(auditSessionSchema))).data;
  },
  async valuation(id: number) {
    const result = await auditCall(
      { method: "GET", path: `${base}/${id}`, query: { valuation: true } },
      envelope(auditSessionSchema),
    );
    if (!result.data.valuation_review) throw new FinoraApiError("invalid_response");
    return result.data.valuation_review;
  },
  async create(data: {
    idempotency_key: string;
    ledger_kind: "branch" | "warehouse";
    location_keys: string[];
    title: string;
  }) {
    return (await auditCall({ method: "POST", path: base, body: data }, envelope(commandSchema))).data;
  },
  async lines(
    id: number,
    query: {
      q?: string;
      location_key?: string;
      counted?: boolean;
      status?: string;
      page?: number;
      page_size?: number;
      exact?: boolean;
    } = {},
  ) {
    return (await auditCall({ method: "GET", path: `${base}/${id}/lines`, query }, envelope(linePageSchema)))
      .data;
  },
  async command(id: number, data: AuditCommand) {
    return (
      await auditCall(
        { method: "POST", path: `${base}/${id}/commands`, body: data },
        envelope(auditReceiptSchema(data.action)),
      )
    ).data;
  },
  async detail(id: number, line: number) {
    return (
      await auditCall(
        { method: "GET", path: `${base}/${id}/lines/${line}/details` },
        envelope(
          z.object({
            line: auditLineSchema,
            investigation: investigationSchema.nullable().optional(),
            investigation_stale: z.boolean().optional(),
          }),
        ),
      )
    ).data;
  },
  async history(id: number, line?: number, page = 1) {
    return (
      await auditCall(
        { method: "GET", path: `${base}/${id}/history`, query: { ...(line ? { line_id: line } : {}), page } },
        envelope(historySchema),
      )
    ).data;
  },
  async movements(id: number, line: number, before_id?: number) {
    return (
      await auditCall(
        {
          method: "GET",
          path: `${base}/${id}/lines/${line}/movements`,
          query: { ...(before_id ? { before_id } : {}) },
        },
        envelope(movementSchema),
      )
    ).data;
  },
};
