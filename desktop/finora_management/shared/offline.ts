import { z } from "zod";
import type { SnapshotStatus } from "./snapshot";
import type { DeviceStockStatus, ReserveStock } from "./stock";

export const supplierDraftSchema = z
  .object({
    supplierId: z.number().int().positive(),
    supplierName: z.string().trim().min(1).max(150),
    items: z
      .array(
        z
          .object({
            product_id: z.number().int().positive(),
            qty: z.number().int().positive().max(2147483647),
            price: z.number().int().positive().max(2147483647),
            variant_color: z.string().max(80).optional(),
          })
          .strict(),
      )
      .min(1)
      .max(100),
    note: z.string().max(255),
    stockMode: z.enum(["draft", "reserved"]).optional(),
  })
  .strict()
  .refine(
    (v) => v.items.reduce((n, i) => n + i.qty * i.price, 0) <= 2147483647,
    "قيمة الفاتورة تتجاوز الحد المسموح",
  );
export type SupplierDraft = z.infer<typeof supplierDraftSchema>;
export const posSaleSchema = z
  .object({
    kind: z.literal("pos"),
    customerId: z.number().int().positive(),
    customerName: z.string().trim().min(1).max(150),
    items: supplierDraftSchema.innerType().shape.items,
    discount: z.number().int().nonnegative().max(2147483647),
    total: z.number().int().positive().max(2147483647),
    payment: z.enum(["cash", "bank", "credit"]),
    accountId: z.number().int().positive().nullable(),
  })
  .strict()
  .refine(
    (v) =>
      v.items.reduce((n, i) => n + i.qty * i.price, 0) <= 2147483647 &&
      v.total === v.items.reduce((n, i) => n + i.qty * i.price, 0) - v.discount &&
      (v.payment === "credit" ? v.accountId === null : v.accountId !== null),
    "قيمة الفاتورة أو حساب التحصيل غير صحيح",
  );
export type PosSale = z.infer<typeof posSaleSchema>;
export interface OfflineOperation {
  id: string;
  label: string;
  total: number;
  createdAt: number;
  status: "pending" | "syncing" | "conflict" | "done" | "cancelled";
  canDiscard?: boolean;
  error: string | null;
  invoiceNo: string | null;
  localInvoiceNo?: string;
  reserved?: boolean;
  kind?: "pos" | "hr" | "finance";
}
export interface OfflineStatus {
  hr?: { ready: boolean; people: number; savedAt: number | null; stale: boolean };
  snapshot?: SnapshotStatus;
  stock?: DeviceStockStatus;
  available: boolean;
  lastVerifiedAt: number | null;
  lastCachedAt: number | null;
  pending: number;
  conflicts: number;
  syncing: boolean;
  error: string | null;
  operations: OfflineOperation[];
}
export interface OfflineBridge {
  savePosSale(id: string, input: PosSale): Promise<{ id: string; localInvoiceNo: string; total: number }>;
  printPosSale(id: string): Promise<void>;
  reserveStock(input: ReserveStock): Promise<OfflineStatus>;
  returnStock(): Promise<OfflineStatus>;
  resumeStockRequest(): Promise<OfflineStatus>;
  downloadSnapshot(restart?: boolean): Promise<OfflineStatus>;
  status(): Promise<OfflineStatus>;
  saveSupplierDraft(input: SupplierDraft): Promise<{ id: string; localInvoiceNo?: string }>;
  synchronize(): Promise<OfflineStatus>;
  retry(id: string): Promise<OfflineStatus>;
  discardHR?(id: string): Promise<OfflineStatus>;
}
