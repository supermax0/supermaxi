import { z } from "zod";
import { desktopBridge } from "@/services/bridge";
import { targetSchema } from "@/features/workspace/state";
import { settle } from "./transport";

const BASE = "/api/v1/desktop/workspace";
const salesSchema = z.object({
  ok: z.literal(true),
  value: z.number(),
  previous: z.number(),
  change: z.number().nullable(),
  date: z.string(),
  captured_at: z.string(),
});
const receivablesSchema = z.object({
  ok: z.literal(true),
  value: z.number(),
  overdue: z.number(),
  debtors: z.number().int(),
  captured_at: z.string(),
});
const activitySchema = z.object({
  ok: z.literal(true),
  rows: z.array(
    z.object({
      id: z.number().int(),
      title: z.string(),
      actor: z.string(),
      at: z.string(),
      target: targetSchema,
      deleted: z.boolean(),
    }),
  ),
  has_more: z.boolean(),
});
export type WorkspaceSales = z.infer<typeof salesSchema>;
export type WorkspaceActivity = z.infer<typeof activitySchema>;
export interface WorkspaceRead<T> {
  value: T;
  cachedAt: number | null;
}
async function read<T>(
  path: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
  query?: Record<string, number>,
): Promise<WorkspaceRead<T>> {
  const response = await desktopBridge().finora.request({ method: "GET", path: `${BASE}/${path}`, query });
  return {
    value: settle(`GET ${BASE}/${path}`, response, schema),
    cachedAt: response.ok && response.source === "offline" ? (response.cachedAt ?? null) : null,
  };
}
export const workspaceApi = {
  sales: () => read("sales", salesSchema),
  receivables: () => read("receivables", receivablesSchema),
  shipping: () =>
    read("shipping", z.object({ ok: z.literal(true), open_manifests: z.number().int().nonnegative() })),
  activity: (before = 0) => read("activity", activitySchema, before ? { before } : undefined),
  assistant: async () => {
    const response = await desktopBridge().finora.request({
      method: "GET",
      path: "/finora-ai/api/desktop/runtime",
    });
    if (!response.ok && response.failure === "http" && [403, 404].includes(response.status ?? 0)) return null;
    return settle(
      "assistant runtime",
      response,
      z.object({ success: z.literal(true), ready: z.boolean(), read_only: z.boolean(), notice: z.string() }),
    );
  },
  ask: async (message: string) => {
    const response = await desktopBridge().finora.request({
      method: "POST",
      path: "/finora-ai/api/desktop/chat",
      body: { message },
      timeoutMs: 60_000,
    });
    return settle("assistant", response, z.object({ success: z.literal(true), message: z.string() }));
  },
};
