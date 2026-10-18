import { z } from "zod";
import { finoraCall } from "./transport";
import { desktopBridge } from "@/services/bridge";
import type { PrintRequest } from "@shared/ipc";

const wholeDinars = z.union([
  z.number().int().safe(),
  z
    .string()
    .max(20)
    .regex(/^-?\d+$/),
]);
export const inventoryActivityRow = z.object({
  id: z
    .number()
    .int()
    .safe()
    .refine((id) => id !== 0),
  record_kind: z.enum(["movement", "capture"]),
  product_id: z.number().int().positive(),
  product_name: z.string(),
  sku: z.string(),
  branch_id: z.number().int().positive(),
  branch_name: z.string(),
  created_at: z.string().datetime(),
  operation: z.string(),
  operation_label: z.string().optional(),
  direction: z.enum(["in", "out"]),
  quantity: z.number().int().positive(),
  variant: z.string(),
  before: z.number().int().nullable(),
  after: z.number().int().nullable(),
  balance_basis: z.enum(["product", "option", "unknown"]),
  actor_name: z.string().nullable(),
  reason: z.string(),
  source_type: z.string().nullable(),
  source_id: z.number().int().nonnegative().nullable(),
  can_open_source: z.boolean(),
  document_kind: z.enum(["invoice", "purchase", "inventory_count", "stock_transfer"]).nullable().optional(),
  document_id: z.number().int().positive().nullable().optional(),
  reversal: z.boolean(),
  unit_cost: wholeDinars.nullable().optional(),
  total_cost: wholeDinars.nullable().optional(),
});
export type InventoryActivityRow = z.infer<typeof inventoryActivityRow>;
const activityPage = z.object({
  available: z.boolean(),
  items: z.array(inventoryActivityRow),
  total: z.number().int().nonnegative(),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
  branches: z.array(z.object({ id: z.number().int().positive(), name: z.string() })),
  can_view_cost: z.boolean(),
  notice: z.string(),
});
export interface InventoryActivityQuery {
  page: number;
  pageSize: number;
  search: string;
  branch: string;
  direction: string;
  from: string;
  to: string;
  productId?: number;
}
function reportFilters(
  query: InventoryActivityQuery,
): Omit<Extract<PrintRequest, { kind: "inventory_activity" }>, "kind"> {
  const filters: Omit<Extract<PrintRequest, { kind: "inventory_activity" }>, "kind"> = {};
  if (query.search) filters.q = query.search;
  if (query.branch) filters.branch_id = Number(query.branch);
  if (query.direction === "in" || query.direction === "out") filters.direction = query.direction;
  if (query.from) filters.from = query.from;
  if (query.to) filters.to = query.to;
  if (query.productId) filters.product_id = query.productId;
  return filters;
}
export const inventoryActivity = {
  print: (query: InventoryActivityQuery) =>
    desktopBridge().print.open({ kind: "inventory_activity", ...reportFilters(query) }),
  async export(query: InventoryActivityQuery) {
    const result = await finoraCall(
      { method: "GET", path: "/api/v1/desktop/inventory-activity/export", query: reportFilters(query) },
      z.object({ success: z.literal(true), data: z.object({ content: z.string(), filename: z.string() }) }),
    );
    return result.data;
  },
  async list(query: InventoryActivityQuery) {
    const filters: Record<string, string | number> = { page: query.page, page_size: query.pageSize };
    if (query.search) filters.q = query.search;
    if (query.branch) filters.branch_id = query.branch;
    if (query.direction) filters.direction = query.direction;
    if (query.from) filters.from = query.from;
    if (query.to) filters.to = query.to;
    if (query.productId) filters.product_id = query.productId;
    const result = await finoraCall(
      { method: "GET", path: "/api/v1/desktop/inventory-activity", query: filters },
      z.object({ success: z.literal(true), data: activityPage }),
    );
    return result.data;
  },
};
