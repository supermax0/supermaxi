/**
 * Orders — routes/orders.py (orders_bp). Server-side pagination, search and
 * filters; status changes go through FINORA's atomic bulk endpoint so stock
 * rules stay in the backend.
 */
import { z } from "zod";
import { desktopBridge } from "@/services/bridge";
import { finoraCall } from "./transport";

export const ORDER_TABS = ["all", "ordered", "packed", "shipping", "delivered", "returned"] as const;
export type OrderTab = (typeof ORDER_TABS)[number];

const text = z
  .string()
  .nullable()
  .optional()
  .transform((value) => (value && value !== "—" ? value : ""));

export const orderRowSchema = z.object({
  id: z.number().int(),
  date: z.string(),
  customer_name: text,
  phone: text,
  phone2: text,
  city: text,
  address: text,
  total: z.number(),
  paid_amount: z.number(),
  remaining: z.number(),
  status: z.string(),
  payment_status: z.string(),
  shipping_company_id: z.number().int().nullable(),
  shipping_company: text,
  shipping_barcode: text,
  delivery_agent_id: z.number().int().nullable(),
  delivery_agent: text,
  employee: text,
  note: text,
  quantity: z.number().int(),
  is_stock_locked: z.boolean(),
  /** FINORA's own verdicts for the row actions (routes/orders.py _order_row). */
  can_pay: z.boolean().optional().default(false),
  can_cancel: z.boolean().optional().default(false),
  can_return: z.boolean().optional(),
});
export type OrderRow = z.infer<typeof orderRowSchema>;

const pageSchema = z.object({
  success: z.literal(true),
  rows: z.array(orderRowSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
  total_amount: z.number(),
});
export type OrdersPage = z.infer<typeof pageSchema>;

const countsSchema = z
  .object({ success: z.literal(true), counts: z.record(z.number().int()) })
  .transform((value) => value.counts as Partial<Record<OrderTab, number>>);

const option = z.object({ id: z.number().int(), name: z.string() });
const lookupsSchema = z.object({
  success: z.literal(true),
  cities: z.array(z.string()),
  shipping_companies: z.array(option),
  delivery_agents: z.array(option),
  branches: z.array(option),
});
export type OrderLookups = z.infer<typeof lookupsSchema>;

const detailsSchema = z.object({
  order: z.object({
    id: z.number().int(),
    customer_id: z.number().int().nullable().optional(),
    customer: z.string().nullable(),
    phone: z.string().nullable(),
    phone2: text,
    city: z.string().nullable(),
    address: z.string().nullable(),
    employee: z.string().nullable(),
    total: z.number().nullable(),
    discount_amount: z.number().nullable().optional(),
    return_summary: z
      .object({
        original_total: z.number().int().nonnegative(),
        credit: z.number().int().nonnegative(),
        net_total: z.number().int().nonnegative(),
        document_ids: z.array(z.number().int().positive()),
        undated_collection_amount: z.number().int().nonnegative().optional(),
      })
      .nullable()
      .optional(),
    paid_amount: z.number().nullable(),
    status: z.string().nullable(),
    payment: z.string().nullable(),
    created_at: z.string(),
    shipping_company: z.string().nullable(),
    shipping_company_id: z.number().int().nullable().optional(),
    shipping_barcode: z.string().nullable().optional(),
    shipping_barcodes: z.array(z.string()).nullable().optional(),
    can_return: z.boolean().optional(),
    note: z.string().nullable(),
    returned_count: z.number().int().nullable().optional(),
    branch_id: z.number().int().nullable().optional(),
    branch_name: z.string().nullable().optional(),
    stock_is_deducted: z.boolean().nullable().optional(),
    is_stock_locked: z.boolean().nullable().optional(),
    can_edit_invoice: z.boolean().optional().default(false),
    can_edit_price: z.boolean().optional().default(false),
    can_edit_customer: z.boolean().optional().default(false),
  }),
  items: z.array(
    z.object({
      id: z.number().int(),
      product_id: z.number().int().nullable().optional(),
      name: z.string().nullable(),
      qty: z.number(),
      returned_qty: z.number().int().nonnegative().optional(),
      remaining_qty: z.number().int().nonnegative().optional(),
      price: z.number().nullable(),
      total: z.number().nullable(),
      variant_color: z.string().nullable().optional(),
      sale_mode: z.string().nullable().optional(),
      storage_source: z
        .object({
          key: z.string(),
          id: z.number().int().positive().nullable(),
          automatic: z.boolean(),
          name: z.string(),
          branch_id: z.number().int().positive(),
        })
        .nullable()
        .optional(),
    }),
  ),
});
export type OrderDetails = z.infer<typeof detailsSchema>;

export interface QuickOrderEdit {
  note: string | null;
  discount_amount: number;
  items: { product_id: number; qty: number; price: number; color: string; sale_mode: string }[];
  customer?: { name: string; phone: string; phone2: string; city: string; address: string };
}

const okSchema = z.object({ success: z.literal(true) }).passthrough();
const quickEditResultSchema = z.object({
  success: z.literal(true),
  stock_locked: z.boolean().optional(),
  stock_lock_reason: text,
});
const paymentResultSchema = z.object({
  success: z.literal(true),
  order: z
    .object({
      id: z.number().int(),
      total: z.number(),
      paid_amount: z.number(),
      remaining: z.number(),
      status: z.string(),
      payment_status: z.string(),
    })
    .optional(),
});
export type PaymentResult = z.infer<typeof paymentResultSchema>;

const shippingBarcodeSchema = z.object({
  success: z.literal(true),
  message: z.string().optional(),
  status_changed: z.boolean().optional(),
  status: z.string().nullable().optional(),
});
export type ShippingBarcodeResult = z.infer<typeof shippingBarcodeSchema>;

const quoteSchema = z
  .object({ ok: z.boolean(), fee: z.number().optional() })
  .transform((value) => (value.ok ? Math.max(0, Math.round(value.fee ?? 0)) : 0));

const branchListSchema = z
  .object({
    ok: z.literal(true),
    branches: z.array(
      z.object({ id: z.number().int(), name: z.string(), is_active: z.boolean().optional() }).passthrough(),
    ),
    scheduled_branch_id: z.number().int().nullable().optional(),
  })
  .transform((value) => ({
    branches: value.branches
      .filter((branch) => branch.id > 0 && branch.is_active !== false)
      .map((branch) => ({ id: branch.id, name: branch.name })),
    scheduledBranchId: value.scheduled_branch_id ?? null,
  }));
export type BranchList = z.infer<typeof branchListSchema>;

const historySchema = z
  .object({
    success: z.literal(true),
    events: z.array(
      z.object({
        id: z.string(),
        created_at: z.string().nullable(),
        movement: z.string(),
        details: z.string().nullable().optional(),
        employee: z.string().nullable().optional(),
        type: z.string().nullable().optional(),
      }),
    ),
  })
  .transform((value) => value.events);
export type OrderHistoryEvent = z.infer<typeof historySchema>[number];

const barcodeSchema = z
  .object({ success: z.literal(true), invoice: z.object({ id: z.number().int() }).passthrough() })
  .transform((value) => value.invoice.id);

/** One collection into a treasury account (≤ 8 per payment, FINORA rule). */
export interface PaymentAllocation {
  treasury_account_id: number;
  amount: number;
}

export interface OrderPayment {
  orderId: number;
  /** full = "مسدد" (collects everything still due), partial = "جزئي". */
  mode: "full" | "partial";
  /** Amount collected now (partial only; full always collects the due). */
  amount: number;
  /** Internal delivery fee line; does not change the invoice total. */
  deliveryFee: number;
  /** Stock branch when the order's stock was not deducted yet. */
  branchId: number | null;
  allocations: PaymentAllocation[];
}
const bulkSchema = z.object({
  success: z.literal(true),
  updated: z.number().int(),
  updated_ids: z.array(z.number().int()),
});

export const returnResultSchema = z.object({
  success: z.literal(true),
  updated: z.number().int().nonnegative(),
  updated_ids: z.array(z.number().int()),
  skipped: z.array(z.object({ id: z.number().int(), message: z.string() })),
  failed: z.array(z.object({ id: z.number().int(), error: z.string() })),
});

export interface OrderFilters {
  search?: string;
  cities?: string[];
  shipping?: string;
  deliveryAgent?: string;
  dateFrom?: string;
  dateTo?: string;
  amountMin?: number;
  amountMax?: number;
}

export interface OrdersQuery extends OrderFilters {
  tab: OrderTab;
  page: number;
  pageSize: number;
  sortField?: "order_id" | "date" | "total" | "customer_name" | "city";
  sortDir?: "asc" | "desc";
}

export function filterParams(filters: OrderFilters): Record<string, string | number | string[]> {
  const params: Record<string, string | number | string[]> = {};
  if (filters.search?.trim()) params.search = filters.search.trim();
  if (filters.cities?.length) params.city = filters.cities;
  if (filters.shipping) params.shipping = filters.shipping;
  if (filters.deliveryAgent) params.delivery_agent = filters.deliveryAgent;
  if (filters.dateFrom) params.date_from = filters.dateFrom;
  if (filters.dateTo) params.date_to = filters.dateTo;
  if (filters.amountMin !== undefined) params.amount_min = filters.amountMin;
  if (filters.amountMax !== undefined) params.amount_max = filters.amountMax;
  return params;
}

export const orders = {
  list(query: OrdersQuery): Promise<OrdersPage> {
    return finoraCall(
      {
        method: "GET",
        path: "/orders/data",
        query: {
          ...filterParams(query),
          page_type: query.tab,
          page: query.page,
          page_size: query.pageSize,
          sort_field: query.sortField ?? "date",
          sort_dir: query.sortDir ?? "desc",
        },
      },
      pageSchema,
    );
  },
  counts(filters: OrderFilters) {
    return finoraCall(
      { method: "GET", path: "/orders/api/counts", query: filterParams(filters) },
      countsSchema,
    );
  },
  lookups(): Promise<OrderLookups> {
    return finoraCall({ method: "GET", path: "/orders/api/lookups" }, lookupsSchema);
  },
  details(id: number): Promise<OrderDetails> {
    return finoraCall({ method: "GET", path: `/orders/details/${id}` }, detailsSchema);
  },
  quickEdit(id: number, input: QuickOrderEdit) {
    return finoraCall(
      { method: "POST", path: `/orders/quick-edit/${id}`, body: { ...input } },
      quickEditResultSchema,
    );
  },
  /** Atomic transition with FINORA's stock checks (allowed: تم الطلب / معباة / جاري الشحن / تم التوصيل). */
  changeStatus(ids: number[], status: string) {
    return finoraCall(
      { method: "POST", path: "/orders/bulk-status", body: { order_ids: ids, status } },
      bulkSchema,
    );
  },
  /** Marks orders returned and restores stock into the chosen branch. */
  markReturned(ids: number[], returnBranchId: number) {
    return finoraCall(
      {
        method: "POST",
        path: "/orders/bulk-return",
        body: { order_ids: ids, return_branch_id: returnBranchId },
      },
      returnResultSchema,
    );
  },
  setShippingCompany(orderId: number, shippingId: number | null) {
    return finoraCall(
      {
        method: "POST",
        path: "/orders/update-shipping",
        body: { order_id: orderId, shipping_id: shippingId },
      },
      okSchema,
    );
  },
  setDeliveryAgent(orderId: number, agentId: number | null) {
    return finoraCall(
      {
        method: "POST",
        path: "/orders/update-delivery-agent",
        body: { order_id: orderId, agent_id: agentId },
      },
      okSchema,
    );
  },
  /** POST /orders/payment — FINORA validates the due, accounts' branch and stock. */
  pay(payment: OrderPayment): Promise<PaymentResult> {
    return finoraCall(
      {
        method: "POST",
        path: "/orders/payment",
        body: {
          id: payment.orderId,
          payment: payment.mode === "full" ? "مسدد" : "جزئي",
          paid_amount: payment.mode === "full" ? null : payment.amount,
          delivery_fee: payment.deliveryFee,
          branch_id: payment.branchId,
          payment_allocations: payment.allocations.length
            ? payment.allocations.map((a) => ({
                treasury_account_id: a.treasury_account_id,
                amount: a.amount,
              }))
            : null,
        },
      },
      paymentResultSchema,
    );
  },
  /**
   * Shipping-company barcodes, one per piece. FINORA moves a "تم الطلب"/"معباة"
   * order to "جاري الشحن" (with its stock checks) when they are saved.
   */
  setShippingBarcodes(
    id: number,
    shippingCompanyId: number,
    barcodes: string[],
  ): Promise<ShippingBarcodeResult> {
    return finoraCall(
      {
        method: "POST",
        path: `/orders/update-shipping-barcode/${id}`,
        body: { shipping_company_id: shippingCompanyId, shipping_barcodes: barcodes },
      },
      shippingBarcodeSchema,
    );
  },
  /** FINORA's suggested delivery fee for the order's province and products. */
  quoteDeliveryFee(city: string, items: Array<{ product_id: number; qty: number }>): Promise<number> {
    return finoraCall(
      { method: "POST", path: "/api/delivery-fee/quote", body: { city, items } },
      quoteSchema,
    );
  },
  branches(): Promise<BranchList> {
    return finoraCall({ method: "GET", path: "/api/branch/list" }, branchListSchema);
  },
  /** Cancels a "تم الطلب" order (FINORA restores stock and reverses payments). */
  cancel(id: number) {
    return finoraCall({ method: "POST", path: `/orders/cancel/${id}`, body: {} }, okSchema);
  },
  history(id: number): Promise<OrderHistoryEvent[]> {
    return finoraCall({ method: "GET", path: `/orders/history/${id}` }, historySchema);
  },
  /** Order id for an invoice / shipping barcode or a scanned order number. */
  findByBarcode(code: string): Promise<number> {
    return finoraCall(
      { method: "GET", path: "/orders/search-by-barcode", query: { barcode: code } },
      barcodeSchema,
    );
  },
  print(ids: number[]): Promise<void> {
    return desktopBridge().print.open({ kind: "orders", ids });
  },
  openInFinora(id: number): Promise<void> {
    return desktopBridge().app.openInFinora(`/orders/${id}`);
  },
};
