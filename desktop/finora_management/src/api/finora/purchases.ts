/**
 * Purchases — routes/purchases.py. FINORA's lifecycle is draft → confirmed
 * (stock applied) → cancelled; "awaiting payment" = confirmed with a remaining
 * balance. Cancelling runs FINORA's own reversal of stock and payments.
 */
import { z } from "zod";
import { desktopBridge } from "@/services/bridge";
import { finoraCall } from "./transport";

export const PURCHASE_TABS = ["all", "draft", "confirmed", "unpaid", "cancelled"] as const;
export type PurchaseTab = (typeof PURCHASE_TABS)[number];

export const purchaseRowSchema = z.object({
  id: z.number().int(),
  invoice_no: z.string(),
  date: z.string(),
  supplier_id: z.number().int().nullable(),
  supplier: z.string(),
  status: z.string(),
  tab: z.enum(["draft", "confirmed", "unpaid", "cancelled"]),
  supplier_invoice_no: z.string(),
  notes: z.string(),
  item_count: z.number().int(),
  first_product: z.string(),
  grand_total: z.number(),
  paid_total: z.number(),
  remaining_total: z.number(),
  purchase_mode: z.string(),
  items: z.array(
    z.object({
      product_id: z.number().int().nullable(),
      product: z.string(),
      color: z.string(),
      quantity: z.number(),
      unit_cost: z.number(),
      line_total: z.number(),
    }),
  ),
  payments: z.array(
    z.object({
      amount: z.number(),
      paid_at: z.string(),
      payment_method: z.string(),
      account_name: z.string(),
      note: z.string(),
    }),
  ),
});
export type PurchaseRow = z.infer<typeof purchaseRowSchema>;

const pageSchema = z.object({
  success: z.literal(true),
  rows: z.array(purchaseRowSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
  counts: z.record(z.number().int()),
  summary: z.object({
    total_amount: z.number(),
    count: z.number().int(),
    draft: z.number().int(),
    unpaid: z.number().int(),
    remaining_amount: z.number(),
  }),
  suppliers: z.array(z.object({ id: z.number().int(), name: z.string() })),
});
export type PurchasesPage = z.infer<typeof pageSchema>;

const cancelSchema = z.object({ success: z.literal(true), message: z.string().optional() });

const colorSchema = z.object({
  name: z.string(),
  qty: z.number().nullable().optional(),
  id: z.number().optional(),
  buy_price: z.number().nullable().optional(),
  image_url: z.string().optional(),
  active: z.boolean().optional(),
});
export const purchaseProductSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  sku: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? ""),
  barcode: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? ""),
  buy_price: z.number(),
  quantity: z.number(),
  has_colors: z.boolean().optional().default(false),
  colors: z.array(colorSchema).optional().default([]),
});
export type PurchaseProduct = z.infer<typeof purchaseProductSchema>;

const createdSchema = z.object({
  success: z.literal(true),
  purchase_id: z.number().int(),
  invoice_no: z.string(),
  message: z.string().optional(),
});

const supplierCreatedSchema = z
  .object({ success: z.literal(true), supplier: z.object({ id: z.number().int(), name: z.string() }) })
  .transform((v) => v.supplier);

export interface NewPurchaseLine {
  product_id: number;
  quantity: number;
  unit_cost_before_discount: number;
  discount_value: number;
  color?: string;
}

export interface NewPurchasePayment {
  amount: number;
  payment_method: "cash" | "bank";
  treasury_account_id?: number;
}

export interface NewPurchase {
  supplierId: number;
  purchaseDate: string;
  mode: "cash" | "credit" | "bank";
  confirm: boolean;
  supplierInvoiceNo: string;
  notes: string;
  discount: number;
  shippingExtra: number;
  lines: NewPurchaseLine[];
  payments: NewPurchasePayment[];
}

export interface PurchasesQuery {
  tab: PurchaseTab;
  page: number;
  pageSize: number;
  search?: string;
  supplierId?: number;
  dateFrom?: string;
  dateTo?: string;
}

export const purchases = {
  async details(id: number): Promise<PurchaseRow> {
    const record = await finoraCall(
      { method: "GET", path: `/purchases/api/${id}` },
      purchaseRowSchema.omit({ tab: true, first_product: true }),
    );
    const tab =
      record.status === "cancelled"
        ? "cancelled"
        : record.status === "draft" || record.status === "draft_editing"
          ? "draft"
          : record.remaining_total > 0
            ? "unpaid"
            : "confirmed";
    return { ...record, tab, first_product: record.items[0]?.product ?? "" };
  },
  list(query: PurchasesQuery): Promise<PurchasesPage> {
    const params: Record<string, string | number> = {
      tab: query.tab,
      page: query.page,
      page_size: query.pageSize,
    };
    if (query.search?.trim()) params.search = query.search.trim();
    if (query.supplierId) params.supplier_id = query.supplierId;
    if (query.dateFrom) params.date_from = query.dateFrom;
    if (query.dateTo) params.date_to = query.dateTo;
    return finoraCall({ method: "GET", path: "/purchases/api/page", query: params }, pageSchema);
  },
  /** FINORA's purchase product picker (barcode exact match first, then name/SKU). */
  searchProducts(q: string): Promise<PurchaseProduct[]> {
    return finoraCall(
      { method: "GET", path: "/purchases/api/products/search", query: { q } },
      z.array(purchaseProductSchema),
    );
  },
  /** POST /purchases/create — FINORA prices lines, applies stock when confirmed and records payments. */
  create(input: NewPurchase) {
    const items = input.lines.map((line) => {
      const item: Record<string, string | number> = {
        product_id: line.product_id,
        quantity: line.quantity,
        unit_cost_before_discount: line.unit_cost_before_discount,
        discount_value: line.discount_value,
      };
      if (line.color) item.color = line.color;
      return item;
    });
    const payments = input.payments.map((payment) => {
      const row: Record<string, string | number> = {
        amount: payment.amount,
        payment_method: payment.payment_method,
      };
      if (payment.treasury_account_id) row.treasury_account_id = payment.treasury_account_id;
      return row;
    });
    return finoraCall(
      {
        method: "POST",
        path: "/purchases/create",
        timeoutMs: 30_000,
        body: {
          supplier_id: input.supplierId,
          purchase_date: input.purchaseDate,
          purchase_mode: input.mode,
          status: input.confirm ? "confirmed" : "draft",
          supplier_invoice_no: input.supplierInvoiceNo.trim(),
          notes: input.notes.trim(),
          discount_value: input.discount,
          shipping_extra: input.shippingExtra,
          items,
          payments,
        },
      },
      createdSchema,
    );
  },
  quickCreateSupplier(supplier: { name: string; phone: string }) {
    return finoraCall(
      {
        method: "POST",
        path: "/suppliers/api/quick-create",
        body: { name: supplier.name.trim(), phone: supplier.phone.trim() },
      },
      supplierCreatedSchema,
    );
  },
  cancel(id: number) {
    return finoraCall({ method: "POST", path: `/purchases/api/${id}/cancel`, body: {} }, cancelSchema);
  },
  print(id: number): Promise<void> {
    return desktopBridge().print.open({ kind: "purchase", id });
  },
  openEditor(id: number): Promise<void> {
    return desktopBridge().app.openInFinora(`/purchases/edit/${id}`);
  },
};
