import { z } from "zod";
import { finoraCall, settle, acknowledgeCustomerCommand } from "./transport";
import { desktopBridge } from "@/services/bridge";

const customer = z.object({
  id: z.number().int().positive(),
  name: z.string(),
  phone: z.string(),
  phone2: z.string(),
  city: z.string(),
  address: z.string(),
  notes: z.string(),
  branch_id: z.number().nullable(),
  debt: z.number().nonnegative(),
  overdue: z.number().nonnegative(),
  created_at: z.string().nullable(),
  revision: z.string().regex(/^[a-f0-9]{64}$/),
});
export type CustomerRow = z.infer<typeof customer>;
export type CustomerFields = Pick<CustomerRow, "name" | "phone" | "phone2" | "city" | "address" | "notes">;
export type CustomerTab = "all" | "debt" | "overdue" | "settled";
const paging = {
  total: z.number().int().nonnegative(),
  page: z.number().int().positive(),
  page_size: z.number().int().positive(),
};
const invoice = z.object({
  id: z.number(),
  number: z.string(),
  date: z.string().nullable(),
  status: z.string(),
  payment_status: z.string(),
  total: z.number(),
  paid: z.number(),
});
const installment = z.object({
  id: z.number(),
  plan_id: z.number(),
  invoice_id: z.number().nullable(),
  number: z.number(),
  date: z.string(),
  total: z.number(),
  paid: z.number(),
  remaining: z.number(),
  status: z.string(),
});
const receivable = z.object({
  kind: z.enum(["invoice", "credit_plan"]),
  id: z.number().int().positive(),
  branch_id: z.number().int().positive().nullable().optional().default(null),
  invoice_id: z.number().int().positive().nullable(),
  date: z.string().nullable(),
  description: z.string(),
  total: z.number(),
  paid: z.number(),
  remaining: z.number().nonnegative(),
});
const envelope = <T extends z.ZodTypeAny>(schema: T) =>
  z.object({ success: z.literal(true), data: schema }).transform((row) => row.data as z.infer<T>);
const get = <T extends z.ZodTypeAny>(path: string, schema: T, query?: Record<string, string | number>) =>
  finoraCall({ method: "GET", path: `/api/v1/desktop/customers${path}`, query }, envelope(schema));

const scheduleRow = z.object({
  id: z.number().int().positive(),
  number: z.number().int().positive(),
  date: z.string(),
  total: z.number().int().nonnegative(),
  paid: z.number().int().nonnegative(),
});
const schedule = z.object({
  id: z.number().int().positive(),
  customer_id: z.number().int().positive(),
  invoice_id: z.number().int().positive().nullable(),
  total: z.number().int().nonnegative(),
  paid: z.number().int().nonnegative(),
  revision: z.string().regex(/^[a-f0-9]{64}$/),
  installments: z.array(scheduleRow),
  protected_ids: z.array(z.number().int().positive()).optional(),
  history_total: z.number().int().nonnegative(),
  history: z.array(
    z.object({
      id: z.number().int().positive(),
      actor: z.string(),
      date: z.string(),
      reason: z.string(),
      before: z.array(scheduleRow),
      after: z.array(scheduleRow),
    }),
  ),
});
export type CustomerSchedule = z.infer<typeof schedule>;
export type ScheduleEdit = {
  revision: string;
  reason: string;
  installments: { id: number; date: string; total: number }[];
};
export type SchedulePartition = {
  revision: string;
  reason: string;
  count: number;
  first_due_date: string;
  interval: "monthly" | "weekly";
};
export type OpeningDebt = SchedulePartition & {
  source_type: "opening";
  source_reference: string;
  amount: number;
};
const debtDraft = z.object({
  customer_id: z.number().int().positive(),
  total: z.number().int(),
  paid: z.number().int(),
  revision: z.string().regex(/^[a-f0-9]{64}$/),
  eligible: z.boolean(),
  blocked_reason: z.string(),
});
const planDraft = z.object({
  customer_id: z.number().int().positive(),
  invoice_id: z.number().int().positive(),
  total: z.number().int(),
  paid: z.number().int(),
  revision: z.string().regex(/^[a-f0-9]{64}$/),
  plan_id: z.number().int().positive().nullable(),
  eligible: z.boolean(),
  blocked_reason: z.string(),
  historical: z
    .object({
      date: z.string(),
      paid: z.number().int().nonnegative(),
      payment_count: z.number().int().nonnegative(),
      vouchers: z
        .array(
          z.object({
            id: z.number().int().positive(),
            number: z.string(),
            date: z.string(),
            amount: z.number().int().positive(),
            reversed: z.boolean(),
          }),
        )
        .default([]),
    })
    .nullable()
    .optional(),
});
const transaction = z.object({
  kind: z.enum(["voucher", "invoice_payment", "debt_payment"]),
  id: z.number().int().positive(),
  date: z.string().nullable(),
  description: z.string(),
  document: z.string(),
  amount: z.number().int(),
  cash: z.number().int().nullable(),
  debt_change: z.number().int(),
  advance_change: z.number().int(),
  invoice_id: z.number().int().positive().nullable(),
  plan_id: z.number().int().positive().nullable(),
  voucher_id: z.number().int().positive().nullable(),
  status: z.string(),
  note: z.string().nullable(),
});
export type CustomerTransaction = z.infer<typeof transaction>;
const historicalRow = transaction.extend({
  kind: z.enum(["voucher", "invoice_payment", "debt_payment", "debt_origin"]),
  net_change: z.number(),
  debt_balance: z.number().nullable(),
  advance_balance: z.number().nullable(),
  net_balance: z.number().nullable(),
});
export type CustomerHistoricalRow = z.infer<typeof historicalRow>;

export const customers = {
  accountHistory: (
    id: number,
    page: number,
    pageSize: number,
    dates: { date_from?: string; date_to?: string },
  ) =>
    get(
      `/${id}/account-history`,
      z.object({
        ...paging,
        items: z.array(historicalRow),
        as_of: z.string(),
        summary: z.object({
          debt: z.number(),
          advance: z.number(),
          net_due: z.number(),
          unexplained_documents: z.number(),
          unexplained_amount: z.number(),
          opening_net: z.number().nullable(),
          closing_net: z.number().nullable(),
          debits: z.number(),
          credits: z.number(),
        }),
        coverage: z.object({
          complete: z.boolean(),
          missing_origins: z.number(),
          archived_documents: z.number(),
          malformed_sources: z.number(),
          undated_movements: z.number(),
          unplaced_debt: z.number(),
          unplaced_advance: z.number(),
          balance_basis: z.literal("day_end"),
          date_from: z.string().nullable(),
          date_to: z.string().nullable(),
        }),
      }),
      { page, page_size: pageSize, ...dates },
    ),
  exportAccountHistory: (id: number, dates: { date_from?: string; date_to?: string }) =>
    get(`/${id}/account-history/export`, z.object({ content: z.string(), filename: z.string() }), dates),
  printAccountHistory: (id: number, dates: { date_from?: string; date_to?: string }) =>
    desktopBridge().print.open({ kind: "customer_history", id, ...dates }),
  savedCommands: () =>
    desktopBridge().customerRecovery?.list() ?? Promise.resolve({ available: false, items: [] }),
  recoverCommand: async (key: string) => {
    const bridge = desktopBridge().customerRecovery;
    if (!bridge) throw Error("حدّث تطبيق FINORA لاسترجاع طلبات الحفظ");
    const { request, response } = await bridge.retry(key);
    const id = request.path.endsWith("/commands")
      ? settle(request.path, response, envelope(customer)).id
      : settle(request.path, response, envelope(schedule)).customer_id;
    await acknowledgeCustomerCommand(request, response);
    return id;
  },
  transactions: (id: number, page: number, pageSize: number) =>
    get(
      `/${id}/transactions`,
      z.object({
        ...paging,
        items: z.array(transaction),
        as_of: z.string(),
        summary: z.object({
          debt: z.number(),
          advance: z.number(),
          net_due: z.number(),
          unexplained_documents: z.number(),
          unexplained_amount: z.number(),
        }),
      }),
      { page, page_size: pageSize },
    ),
  exportTransactions: (id: number) =>
    get(`/${id}/transactions/export`, z.object({ content: z.string(), filename: z.string() })),
  printTransactions: (id: number) => desktopBridge().print.open({ kind: "customer_transactions", id }),
  schedule: (customerId: number, planId: number) => get(`/${customerId}/plans/${planId}`, schedule),
  debtDraft: (customerId: number) => get(`/${customerId}/debts`, debtDraft),
  createDebt: (customerId: number, data: OpeningDebt, key: string) =>
    finoraCall(
      {
        method: "POST",
        path: `/api/v1/desktop/customers/${customerId}/debts`,
        body: { ...data, idempotency_key: key },
      },
      envelope(schedule),
    ),
  planDraft: (customerId: number, invoiceId: number) =>
    get(`/${customerId}/invoices/${invoiceId}/schedule`, planDraft),
  buildPlan: (customerId: number, sourceId: number, create: boolean, data: SchedulePartition, key: string) =>
    finoraCall(
      {
        method: "POST",
        path: `/api/v1/desktop/customers/${customerId}/${create ? `invoices/${sourceId}/schedule` : `plans/${sourceId}/repartition`}`,
        body: { ...data, idempotency_key: key },
      },
      envelope(schedule),
    ),
  reschedule: (customerId: number, planId: number, data: ScheduleEdit, key: string) =>
    finoraCall(
      {
        method: "POST",
        path: `/api/v1/desktop/customers/${customerId}/plans/${planId}/schedule`,
        body: { ...data, idempotency_key: key },
      },
      envelope(schedule),
    ),
  printStatement: (id: number) => desktopBridge().print.open({ kind: "customer_statement", id }),
  save: (data: CustomerFields, key: string, row?: CustomerRow) =>
    finoraCall(
      {
        method: "POST",
        path: "/api/v1/desktop/customers/commands",
        body: {
          operation: row ? "update" : "create",
          idempotency_key: key,
          data,
          ...(row ? { id: row.id, revision: row.revision } : {}),
        },
      },
      envelope(customer),
    ),
  list: (query: { q: string; tab: CustomerTab; page: number; page_size: number }) =>
    get(
      "",
      z.object({
        ...paging,
        items: z.array(customer),
        as_of: z.string(),
        stats: z.object({
          customers: z.number(),
          debt: z.number(),
          overdue: z.number(),
          debtors: z.number(),
        }),
      }),
      query,
    ),
  detail: (id: number) => get(`/${id}`, customer),
  receivables: (id: number, page: number) =>
    get(
      `/${id}/history`,
      z.object({
        ...paging,
        items: z.array(receivable),
        as_of: z.string(),
        summary: z.object({ total: z.number(), paid: z.number(), remaining: z.number() }),
      }),
      { kind: "receivables", page, page_size: 25 },
    ),
  invoices: (id: number, page: number) =>
    get(`/${id}/history`, z.object({ ...paging, items: z.array(invoice) }), {
      kind: "invoices",
      page,
      page_size: 25,
    }),
  installments: (id: number, page: number) =>
    get(`/${id}/history`, z.object({ ...paging, items: z.array(installment) }), {
      kind: "installments",
      page,
      page_size: 25,
    }),
};
