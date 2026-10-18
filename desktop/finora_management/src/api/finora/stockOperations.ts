import { z } from "zod";
import type { FinoraRequest } from "@shared/ipc";
import { desktopBridge } from "@/services/bridge";
import { FinoraApiError } from "./errors";
import { finoraCall, settle } from "./transport";
import { storageCommandResult } from "./storageLocations";
export type StockLedger = "branch" | "warehouse";
export type StockDocument = "transfers" | "writeoffs";
export type StockPayload = Extract<NonNullable<FinoraRequest["body"]>, Record<string, unknown>>;
const base = "/api/v1/desktop/stock-operations";
const wholeDinars = z.union([z.number().int().safe(), z.string().max(20).regex(/^\d+$/)]);
const place = z.object({
  key: z.string(),
  branch_id: z.number().int().positive(),
  warehouse_id: z.number().int().positive().nullable(),
  name: z.string(),
  branch_name: z.string(),
});
const meta = z.object({
  kind: z.enum(["branch", "warehouse"]),
  kinds: z.array(z.enum(["branch", "warehouse"])),
  locations: z.array(place),
  branches: z.array(place),
  today: z.string(),
  can_create_transfer: z.boolean(),
  can_send: z.boolean(),
  can_receive: z.boolean(),
  can_writeoff: z.boolean(),
  can_edit_rules: z.boolean(),
  can_manage_locations: z.boolean(),
  show_cost: z.boolean(),
  storage_available: z.boolean().optional(),
});
export const stockRow = z.object({
  id: z.number().int().safe(),
  product_id: z.number().int().positive(),
  variant_id: z.number().int().positive().nullable(),
  name: z.string(),
  sku: z.string(),
  barcode: z.string(),
  image_url: z.string(),
  variant_name: z.string(),
  unit: z.string(),
  unit_cost: wholeDinars.optional(),
  location_key: z.string(),
  location_name: z.string(),
  quantity: z.number().int().nonnegative(),
  available: z.number().int().nonnegative(),
  reserved: z.number().int().nonnegative(),
  in_transit: z.number().int().nonnegative(),
  minimum: z.number().int().nonnegative(),
  target: z.number().int().nonnegative(),
  rule_version: z.number().int().nonnegative(),
  suggested: z.number().int().nonnegative(),
  revision: z.string(),
  valuation_ready: z.boolean(),
});
const page = {
  total: z.number().int().nonnegative(),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
};
const transfer = z.object({
  id: z.number().int().positive(),
  ledger_kind: z.enum(["branch", "warehouse"]),
  number: z.string(),
  from_location: z.string(),
  to_location: z.string(),
  from_name: z.string(),
  to_name: z.string(),
  status: z.enum(["draft", "approved", "sent", "partially_received", "received", "rejected", "cancelled"]),
  quantity: z.number().int().nonnegative(),
  note: z.string(),
  created_at: z.string().nullable(),
  revision: z.string(),
});
const detail = transfer.extend({
  can_send: z.boolean(),
  can_receive: z.boolean(),
  can_cancel: z.boolean(),
  /** Branch transfers only (the warehouse ledger never sends these). */
  approval_required: z.boolean().optional(),
  can_approve: z.boolean().optional(),
  can_reject: z.boolean().optional(),
  can_receive_partial: z.boolean().optional(),
  can_resolve: z.boolean().optional(),
  lines: z.array(
    z.object({
      id: z.number().int().positive(),
      product_id: z.number().int().positive(),
      name: z.string(),
      variant_name: z.string(),
      quantity: z.number().int().positive(),
      received: z.number().int().nonnegative(),
      sent: z.number().int().nonnegative().optional(),
      /** Still on the road: sent, neither received nor returned. */
      residual: z.number().int().nonnegative().optional(),
      cost: wholeDinars.nullable(),
    }),
  ),
});
const writeoff = z.object({
  id: z.number().int().positive(),
  number: z.string(),
  ledger_kind: z.enum(["branch", "warehouse"]),
  location_key: z.string(),
  location_name: z.string(),
  product_id: z.number().int().positive(),
  product_name: z.string(),
  variant_name: z.string(),
  quantity: z.number().int().positive(),
  cost: wholeDinars.nullable(),
  reason: z.string(),
  business_date: z.string(),
  before_quantity: z.number().int().nonnegative(),
  after_quantity: z.number().int().nonnegative(),
  reversal_of_id: z.number().int().positive().nullable(),
  status: z.enum(["posted", "reversed", "reversal"]),
  revision: z.string(),
});
const result = z.object({
  success: z.literal(true),
  data: z.object({
    id: z.number().int().positive(),
    type: z.string(),
    ledger_kind: z.enum(["branch", "warehouse"]),
    status: z.string(),
  }),
  operation_id: z.string().uuid(),
});
export type StockRow = z.infer<typeof stockRow>;
export type StockMeta = z.infer<typeof meta>;
export type StockTransfer = z.infer<typeof transfer>;
export type StockTransferDetail = z.infer<typeof detail>;
export type StockWriteOff = z.infer<typeof writeoff>;
const movement = z.object({
  id: z.number().int().positive(),
  product_id: z.number().int().positive(),
  product_name: z.string(),
  quantity: z.number().int(),
  before: z.number().int().nullable(),
  after: z.number().int().nullable(),
  operation: z.string(),
  created_at: z.string(),
  note: z.string(),
  document: z.enum(["transfers", "writeoffs"]).nullable(),
  document_id: z.number().int().positive().nullable(),
  cost: wholeDinars.nullable(),
});
export type StockWarehouseMovement = z.infer<typeof movement>;
async function get<T>(path: string, schema: z.ZodType<T>, query: Record<string, string | number> = {}) {
  const reply = await finoraCall(
    { method: "GET", path: `${base}${path}`, query, timeoutMs: 30000 },
    z.object({ success: z.literal(true), data: schema }),
  );
  if (reply.data === undefined) throw new FinoraApiError("invalid_response");
  return reply.data;
}
async function save(path: string, body: StockPayload) {
  const bridge = desktopBridge();
  if (!bridge.stockRecovery)
    throw new FinoraApiError("refused", { message: "أعد تشغيل FINORA المحدث لتفعيل حفظ المخزون الآمن" });
  const response = await bridge.finora.request({
    method: "POST",
    path: `${base}${path}`,
    body,
    timeoutMs: 30000,
  });
  const parsed = settle("عملية مخزون", response, result);
  if (response.ok && response.customerCommandScope)
    await bridge.stockRecovery.acknowledge({
      key: String(body.operation_id),
      path: `${base}${path}`,
      scope: response.customerCommandScope,
    });
  return parsed.data;
}
export const stockOperations = {
  meta: (kind: StockLedger) => get("/meta", meta, { kind }),
  item: (kind: StockLedger, location: string, product_id: number, variant_name: string) =>
    get("/item", stockRow, { kind, location, product_id, variant_name }),
  valuation: (
    kind: StockLedger,
    location: string,
    product_id: number,
    variant_name: string,
    quantity: number,
  ) =>
    get(
      "/valuation",
      z.object({
        cost: wholeDinars.nullable(),
        quantity: z.number(),
        available: z.number(),
        stock_revision: z.string(),
        eligible: z.boolean(),
        blocked_reason: z.string(),
      }),
      { kind, location, product_id, variant_name, quantity },
    ),
  stocks: (kind: StockLedger, location: string, q: string, pageNumber = 1, pageSize = 25, reorder = false) =>
    get(
      "/stocks",
      z.object({
        ...page,
        items: z.array(stockRow),
        stats: z.object({
          items: z.number(),
          quantity: z.number(),
          reserved: z.number(),
          reorder: z.number(),
        }),
      }),
      { kind, location, q, page: pageNumber, page_size: pageSize, reorder: reorder ? "1" : "0" },
    ),
  transfers: (kind: StockLedger, q: string, status: string, pageNumber = 1, pageSize = 25, location = "") =>
    get("/transfers", z.object({ ...page, items: z.array(transfer) }), {
      kind,
      q,
      status,
      page: pageNumber,
      page_size: pageSize,
      location,
    }),
  transfer: (kind: StockLedger, id: number) => get(`/${kind}/transfers/${id}`, detail),
  movements: (location: string, product_id: number | undefined, pageNumber = 1, pageSize = 25) =>
    get("/warehouse/movements", z.object({ ...page, items: z.array(movement) }), {
      location,
      page: pageNumber,
      page_size: pageSize,
      ...(product_id ? { product_id } : {}),
    }),
  createTransfer: (kind: StockLedger, body: StockPayload) => save(`/${kind}/transfers`, body),
  transferPhase: (
    kind: StockLedger,
    id: number,
    phase: "send" | "receive" | "cancel" | "approve" | "reject" | "receive_partial" | "resolve",
    body: StockPayload,
  ) => save(`/${kind}/transfers/${id}/${phase}`, body),
  writeoffs: (kind: StockLedger, location: string, q: string, pageNumber = 1, pageSize = 25) =>
    get("/writeoffs", z.object({ ...page, items: z.array(writeoff) }), {
      kind,
      location,
      q,
      page: pageNumber,
      page_size: pageSize,
    }),
  writeoff: (id: number) => get(`/writeoffs/${id}`, writeoff),
  createWriteoff: (kind: StockLedger, body: StockPayload) => save(`/${kind}/writeoffs`, body),
  reverseWriteoff: (id: number, body: StockPayload) => save(`/writeoffs/${id}/reverse`, body),
  rule: (kind: StockLedger, body: StockPayload) => save(`/${kind}/rules`, body),
  createWarehouse: (body: StockPayload) => save("/warehouse/locations", body),
  print: (ledger: StockLedger, document: StockDocument, id: number) =>
    desktopBridge().print.open({ kind: "stock_document", ledger, document, id }),
  async pending() {
    const bridge = desktopBridge().stockRecovery;
    return bridge ? bridge.list() : { available: false, items: [], error: "أعد تشغيل نسخة FINORA المحدثة" };
  },
  async retry(key: string) {
    const bridge = desktopBridge().stockRecovery;
    if (!bridge) throw new FinoraApiError("refused", { message: "التحديث يحتاج إعادة تشغيل البرنامج" });
    const recovered = await bridge.retry(key);
    if (recovered.request.path.startsWith(`${base}/storage/`)) {
      const parsed = settle("مراجعة طلب المخزن", recovered.response, storageCommandResult);
      if (
        parsed.type !==
        (recovered.request.path.startsWith(`${base}/storage/locations`)
          ? "storage_location"
          : "storage_transfer")
      )
        throw new FinoraApiError("invalid_response");
      if (!recovered.response.ok || !recovered.response.customerCommandScope)
        throw new FinoraApiError("invalid_response", {
          message: "تعذر تثبيت تأكيد العملية؛ راجع طلبات المخزون المحفوظة",
        });
      await bridge.acknowledge({
        key,
        path: recovered.request.path,
        scope: recovered.response.customerCommandScope,
      });
      return parsed;
    }
    const parsed = settle("مراجعة طلب المخزون", recovered.response, result);
    if (recovered.response.ok && recovered.response.customerCommandScope)
      await bridge.acknowledge({
        key,
        path: recovered.request.path,
        scope: recovered.response.customerCommandScope,
      });
    return parsed.data;
  },
};
