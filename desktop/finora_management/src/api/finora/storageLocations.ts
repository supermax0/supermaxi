/** Core storage subdivides branch FIFO. Activation waits for every stock consumer's integration. */
import { z } from "zod";
import { finoraCall } from "./transport";
import { settle } from "./transport";
import { desktopBridge } from "@/services/bridge";
import { FinoraApiError } from "./errors";
import type { StockPayload } from "./stockOperations";

const siteKind = z.enum(["main", "storage", "sales", "damaged", "returns"]);
const location = z.object({
  id: z.number().int().nullable(),
  key: z.string(),
  branch_id: z.number().int().positive(),
  branch_name: z.string(),
  code: z.string(),
  name: z.string(),
  kind: siteKind,
  is_active: z.boolean(),
  revision: z.string().nullable(),
});
const state = z.object({
  product_id: z.number().int().positive(),
  variant_name: z.string(),
  location_id: z.number().int().nullable(),
  quantity: z.number().int(),
  available: z.number().int().nonnegative(),
  movable: z.number().int().nonnegative(),
  basis_valid: z.boolean(),
  cost: z.number().int().safe().nullable(),
  revision: z.string(),
});
const stock = state.extend({
  id: z.number().int().positive(),
  name: z.string(),
  sku: z.string(),
  barcode: z.string(),
  image_url: z.string(),
  model: z.string(),
  variant_id: z.number().int().nullable(),
  unit: z.string(),
});
const document = z.object({
  id: z.number().int().positive(),
  number: z.string(),
  branch_id: z.number().int().positive(),
  branch_name: z.string(),
  from_location_id: z.number().int().nullable(),
  to_location_id: z.number().int().nullable(),
  from_name: z.string(),
  to_name: z.string(),
  product_id: z.number().int().positive(),
  product_name: z.string(),
  sku: z.string(),
  image_url: z.string(),
  variant_name: z.string(),
  quantity: z.number().int().positive(),
  reason: z.string(),
  status: z.enum(["draft", "sent", "received", "cancelled"]),
  revision: z.string(),
  created_at: z.string(),
  cost: z.number().int().safe().nullable(),
  can_send: z.boolean().optional(),
  can_receive: z.boolean().optional(),
  can_cancel: z.boolean().optional(),
  source: state.nullable().optional(),
  layers: z
    .array(
      z.object({
        sequence: z.number().int(),
        quantity: z.number().int().positive(),
        unit_cost: z.number().int().nonnegative(),
        original_created_at: z.string().nullable(),
      }),
    )
    .optional(),
});
const envelope = <T extends z.ZodTypeAny>(data: T) =>
  z.object({ success: z.literal(true), data }).transform((reply): z.infer<T> => reply.data);
export type StoragePlace = z.infer<typeof location>;
export type StorageStock = z.infer<typeof stock>;
export type StorageDocument = z.infer<typeof document>;
export type StorageState = z.infer<typeof state>;
const root = "/api/v1/desktop/stock-operations/storage";
export const storageCommandResult = envelope(
  z.discriminatedUnion("type", [
    z.object({ id: z.number().int().positive(), type: z.literal("storage_location"), location }),
    z.object({ id: z.number().int().positive(), type: z.literal("storage_transfer"), document }),
  ]),
);
async function save(path: string, body: StockPayload) {
  const bridge = desktopBridge();
  if (!bridge.stockRecovery)
    throw new FinoraApiError("refused", { message: "أعد تشغيل FINORA المحدث لتفعيل حفظ المخزون الآمن" });
  const response = await bridge.finora.request({
    method: "POST",
    path: `${root}${path}`,
    body,
    timeoutMs: 30000,
  });
  const result = settle("عملية مخزن", response, storageCommandResult);
  if (result.type !== (path.startsWith("/locations") ? "storage_location" : "storage_transfer"))
    throw new FinoraApiError("invalid_response");
  if (!response.ok || !response.customerCommandScope)
    throw new FinoraApiError("invalid_response", {
      message: "تعذر تثبيت تأكيد العملية؛ راجع طلبات المخزون المحفوظة",
    });
  await bridge.stockRecovery.acknowledge({
    key: String(body.operation_id),
    path: `${root}${path}`,
    scope: response.customerCommandScope,
  });
  return result;
}

export const storageLocations = {
  createLocation: (body: StockPayload) => save("/locations", body),
  updateLocation: (id: number, body: StockPayload) => save(`/locations/${id}`, body),
  createTransfer: (body: StockPayload) => save("/transfers", body),
  transferPhase: (id: number, phase: "send" | "receive" | "cancel", body: StockPayload) =>
    save(`/transfers/${id}/${phase}`, body),
  meta: () =>
    finoraCall(
      { method: "GET", path: `${root}/meta` },
      envelope(z.object({ places: z.array(location), can_edit: z.boolean(), show_cost: z.boolean() })),
    ),
  stocks: (branchId: number, locationId: number | null, page = 1, q = "", pageSize = 25) =>
    finoraCall(
      {
        method: "GET",
        path: `${root}/stocks`,
        query: {
          branch_id: branchId,
          ...(locationId === null ? {} : { location_id: locationId }),
          page,
          page_size: pageSize,
          q,
        },
      },
      envelope(
        z.object({
          items: z.array(stock),
          total: z.number().int().nonnegative(),
          page: z.number().int().positive(),
          page_size: z.number().int().positive(),
        }),
      ),
    ),
  transfers: (branchId: number, page = 1, pageSize = 25) =>
    finoraCall(
      { method: "GET", path: `${root}/transfers`, query: { branch_id: branchId, page, page_size: pageSize } },
      envelope(
        z.object({
          items: z.array(document),
          total: z.number().int().nonnegative(),
          page: z.number().int().positive(),
        }),
      ),
    ),
  document: (id: number) =>
    finoraCall({ method: "GET", path: `${root}/transfers/${id}` }, envelope(document)),
  item: (branchId: number, productId: number, variantName: string, locationId: number | null) =>
    finoraCall(
      {
        method: "GET",
        path: `${root}/item`,
        query: {
          branch_id: branchId,
          product_id: productId,
          variant_name: variantName,
          ...(locationId === null ? {} : { location_id: locationId }),
        },
      },
      envelope(state),
    ),
};
