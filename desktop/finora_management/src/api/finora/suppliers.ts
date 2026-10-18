import { z } from "zod";
import { desktopBridge } from "@/services/bridge";
import { finoraCall } from "./transport";

export const SUPPLIER_TABS = ["all", "debt", "credit", "settled"] as const;
export type SupplierTab = (typeof SUPPLIER_TABS)[number];
export const supplierSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  phone: z.string(),
  phone2: z.string(),
  address: z.string(),
  opening_balance: z.number(),
  total_debt: z.number(),
  total_paid: z.number(),
  remaining: z.number(),
  total_purchases: z.number(),
  purchase_count: z.number().int(),
  payment_count: z.number().int(),
  last_transaction: z.string(),
  created_at: z.string(),
  member_count: z.number().int(),
});
export type SupplierRow = z.infer<typeof supplierSchema>;
const pageSchema = z.object({
  success: z.literal(true),
  rows: z.array(supplierSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
  counts: z.record(z.number().int()),
  summary: z.object({
    count: z.number().int(),
    payable: z.number(),
    credit: z.number(),
    purchases: z.number(),
  }),
});
const invoiceSchema = z.object({
  id: z.number().int(),
  invoice_no: z.string(),
  date: z.string(),
  status: z.string(),
  products_label: z.string(),
  grand_total: z.number(),
  paid_total: z.number(),
  remaining_total: z.number(),
});
const detailsSchema = z.object({
  success: z.literal(true),
  supplier: supplierSchema,
  purchases: z.array(invoiceSchema),
  payments: z.array(
    z.object({
      id: z.number().int(),
      date: z.string(),
      amount: z.number(),
      note: z.string(),
      document_number: z.string(),
      payment_method: z.string(),
      invoice_labels: z.array(z.string()),
    }),
  ),
  sales: z.array(
    z.object({
      id: z.number().int(),
      invoice_no: z.string(),
      date: z.string(),
      grand_total: z.number(),
      products_label: z.string(),
    }),
  ),
  treasury_accounts: z.array(z.object({ id: z.number().int(), name: z.string(), is_default: z.boolean() })),
});
export type SupplierDetails = z.infer<typeof detailsSchema>;
export interface SupplierFields {
  name: string;
  phone: string;
  phone2: string;
  address: string;
  opening_balance?: number;
}
export interface SuppliersQuery {
  tab: SupplierTab;
  search: string;
  page: number;
  pageSize: number;
  sort: "name" | "balance" | "recent";
  minBalance?: number;
}
const savedSchema = z.object({ success: z.literal(true), id: z.number().int(), message: z.string() });
const saleProductSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  sku: z.string(),
  barcode: z.string(),
  sale_price: z.number(),
  quantity: z.number(),
  has_colors: z.boolean(),
  colors: z.array(z.object({ name: z.string(), qty: z.number(), sale_price: z.number() })),
});
export type SupplierSaleProduct = z.infer<typeof saleProductSchema>;
export interface SupplierSaleLine {
  product_id: number;
  qty: number;
  price: number;
  variant_color?: string;
}
const saleSavedSchema = z.object({
  success: z.literal(true),
  message: z.string(),
  sale_id: z.number().int(),
  invoice_no: z.string(),
  grand_total: z.number(),
  remaining: z.number(),
  supplier_receivable: z.number(),
});
export const suppliers = {
  saleProducts(search: string) {
    return finoraCall(
      { method: "GET", path: "/suppliers/api/sale-products", query: { q: search.trim() } },
      z.array(saleProductSchema),
    );
  },
  sell(id: number, items: SupplierSaleLine[], note: string) {
    return finoraCall(
      {
        method: "POST",
        path: `/suppliers/api/${id}/sale`,
        body: { items: items.map((i) => ({ ...i })), note: note.trim() },
        timeoutMs: 30_000,
      },
      saleSavedSchema,
    );
  },
  list(q: SuppliersQuery) {
    return finoraCall(
      {
        method: "GET",
        path: "/suppliers/api/page",
        query: {
          tab: q.tab,
          search: q.search.trim(),
          page: q.page,
          page_size: q.pageSize,
          sort: q.sort,
          min_balance: q.minBalance ?? 0,
        },
      },
      pageSchema,
    );
  },
  details(id: number) {
    return finoraCall({ method: "GET", path: `/suppliers/api/${id}` }, detailsSchema);
  },
  save(fields: SupplierFields, id?: number) {
    return finoraCall(
      {
        method: "POST",
        path: id ? `/suppliers/api/${id}/update` : "/suppliers/api/create",
        body: { ...fields },
      },
      savedSchema,
    );
  },
  pay(
    id: number,
    input: {
      amount: number;
      treasury_account_id: number;
      payment_date: string;
      document_number: string;
      note: string;
    },
  ) {
    return finoraCall({ method: "POST", path: `/suppliers/api/${id}/pay`, body: { ...input } }, savedSchema);
  },
  openAccount(id: number) {
    return desktopBridge().app.openInFinora(`/suppliers/${id}`);
  },
  printStatement(id: number) {
    return desktopBridge().print.open({ kind: "supplier", id });
  },
};
