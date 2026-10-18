/**
 * Point of sale — routes/pos.py + services/pos_checkout.py (the same checkout the
 * web POS uses: FINORA prices every line, applies stock rules and de-duplicates
 * submissions by token). Payment is FINORA's own /orders/payment step.
 */
import { z } from "zod";
import { finoraCall } from "./transport";

const colorSchema = z.object({
  name: z.string(),
  qty: z.number().nullable().optional(),
  sale_price: z.number().nullable().optional(),
  image_url: z.string().optional(),
  active: z.boolean().optional(),
  attributes: z.record(z.string()).optional(),
});

export const posProductSchema = z.object({
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
  price: z.number(),
  quantity: z
    .number()
    .nullable()
    .optional()
    .transform((v) => v ?? 0),
  image_url: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? ""),
  category: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? ""),
  has_colors: z.boolean().optional().default(false),
  colors: z.array(colorSchema).optional().default([]),
  option_axes: z.array(z.string()).optional(),
  has_exchange_sale: z.boolean().optional(),
  exchange_sale_price: z.number().nullable().optional(),
});
export type PosProduct = z.infer<typeof posProductSchema>;
export type PosColor = z.infer<typeof colorSchema>;

const productsPageSchema = z.object({
  success: z.literal(true),
  rows: z.array(posProductSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
  categories: z.array(z.string()),
});
export type PosProductsPage = z.infer<typeof productsPageSchema>;

const bootstrapSchema = z.object({
  success: z.literal(true),
  provinces: z.array(z.string()),
  branch_id: z.number().int().nullable(),
  can_edit_price: z.boolean(),
  can_print: z.boolean(),
  can_pay: z.boolean(),
  storage_sources: z
    .array(
      z.object({
        key: z.string(),
        id: z.number().int().positive().nullable(),
        name: z.string(),
        automatic: z.boolean(),
      }),
    )
    .optional(),
});
export type PosBootstrap = z.infer<typeof bootstrapSchema>;

export const posCustomerSchema = z.object({
  id: z.number().int(),
  name: z
    .string()
    .nullable()
    .transform((v) => v ?? ""),
  phone: z
    .string()
    .nullable()
    .transform((v) => v ?? ""),
  city: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? ""),
  address: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? ""),
  blacklisted: z.boolean().optional().default(false),
  blacklist_message: z
    .string()
    .nullable()
    .optional()
    .transform((v) => v ?? ""),
});
export type PosCustomer = z.infer<typeof posCustomerSchema>;

const addCustomerSchema = z.object({
  status: z.literal("success"),
  id: z.number().int(),
  name: z.string(),
  phone: z.string(),
});

const createOrderSchema = z.object({
  success: z.literal(true),
  invoice_id: z.number().int(),
  total: z.number(),
  updated: z.boolean().optional(),
  stock_locked: z.boolean().optional(),
});
export type CreatedOrder = z.infer<typeof createOrderSchema>;

const accountsSchema = z.object({
  success: z.literal(true),
  accounts: z.array(
    z.object({
      id: z.number().int(),
      name: z.string(),
      type: z.string(),
      is_default: z.boolean(),
      branch_id: z.number().int().nullable(),
      branch_name: z.string().nullable().optional(),
      label: z.string(),
    }),
  ),
});
export type PaymentAccount = z.infer<typeof accountsSchema>["accounts"][number];

export interface NewCustomer {
  name: string;
  phone: string;
  phone2?: string;
  city: string;
  address: string;
}

export interface CheckoutLine {
  product_id: number;
  qty: number;
  price: number;
  color?: string;
  sale_mode?: "normal" | "exchange";
  storage_location_id?: number | null;
  storage_automatic?: boolean;
}

export interface CheckoutInput {
  customerId: number;
  lines: CheckoutLine[];
  discountAmount: number;
  branchId: number | null;
  orderId: number | null;
  submissionToken: string;
}

export const pos = {
  bootstrap(): Promise<PosBootstrap> {
    return finoraCall({ method: "GET", path: "/pos/api/bootstrap" }, bootstrapSchema);
  },
  products(query: {
    page: number;
    pageSize: number;
    search?: string;
    category?: string;
  }): Promise<PosProductsPage> {
    const params: Record<string, string | number> = { page: query.page, page_size: query.pageSize };
    if (query.search?.trim()) params.search = query.search.trim();
    if (query.category) params.category = query.category;
    return finoraCall({ method: "GET", path: "/pos/api/products", query: params }, productsPageSchema);
  },
  searchCustomers(q: string, branchId: number | null): Promise<PosCustomer[]> {
    const query: Record<string, string | number> = { q };
    if (branchId) query.branch_id = branchId;
    return finoraCall({ method: "GET", path: "/pos/search-customer", query }, z.array(posCustomerSchema));
  },
  async addCustomer(customer: NewCustomer, branchId: number | null): Promise<PosCustomer> {
    const body: Record<string, string | number> = {
      name: customer.name.trim(),
      phone: customer.phone.trim(),
      city: customer.city,
      address: customer.address.trim(),
    };
    if (customer.phone2?.trim()) body.phone2 = customer.phone2.trim();
    if (branchId) body.branch_id = branchId;
    const saved = await finoraCall({ method: "POST", path: "/pos/add-customer", body }, addCustomerSchema);
    return {
      id: saved.id,
      name: saved.name,
      phone: saved.phone,
      city: customer.city,
      address: customer.address.trim(),
      blacklisted: false,
      blacklist_message: "",
    };
  },
  createOrder(input: CheckoutInput): Promise<CreatedOrder> {
    const items = input.lines.map((line) => {
      const item: Record<string, string | number | boolean | null> = {
        product_id: line.product_id,
        qty: line.qty,
        price: line.price,
      };
      if (line.color) item.color = line.color;
      if (line.sale_mode) item.sale_mode = line.sale_mode;
      if (line.storage_automatic !== undefined) {
        item.storage_automatic = line.storage_automatic;
        item.storage_location_id = line.storage_location_id ?? null;
      }
      return item;
    });
    const body: Record<
      string,
      string | number | null | Array<Record<string, string | number | boolean | null>>
    > = {
      customer_id: input.customerId,
      items,
      discount_amount: input.discountAmount,
      submission_token: input.submissionToken,
      order_id: input.orderId,
    };
    if (input.branchId) body.branch_id = input.branchId;
    return finoraCall(
      { method: "POST", path: "/pos/create-order", body, timeoutMs: 30_000 },
      createOrderSchema,
    );
  },
  async paymentAccounts(): Promise<PaymentAccount[]> {
    return (await finoraCall({ method: "GET", path: "/orders/payment-accounts" }, accountsSchema)).accounts;
  },
  /** Full collection into one treasury account (FINORA records the cash/bank movement). */
  pay(orderId: number, accountId: number, amount: number) {
    return finoraCall(
      {
        method: "POST",
        path: "/orders/payment",
        body: {
          id: orderId,
          payment: "مسدد",
          payment_allocations: [{ treasury_account_id: accountId, amount }],
        },
      },
      z.object({ success: z.literal(true) }).passthrough(),
    );
  },
};
