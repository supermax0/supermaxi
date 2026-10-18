import { z } from "zod";
import { desktopBridge } from "@/services/bridge";
import { finoraCall, finoraForm } from "./transport";

const audit = z.object({
  action: z.string(),
  at: z.string(),
  created_by: z.number(),
  details: z.record(z.unknown()),
});
const attachment = z.object({ id: z.number(), filename: z.string() });
const option = z.object({ id: z.number(), name: z.string() });
export const accountSchema = option.extend({
  type: z.string(),
  branch_id: z.number().nullable(),
  balance: z.number(),
});
export const voucherSchema = z.object({
  id: z.number(),
  number: z.string(),
  kind: z.string(),
  category: z.string(),
  category_label: z.string(),
  party_type: z.string(),
  party_id: z.number().nullable(),
  party_name: z.string(),
  amount: z.number(),
  account_name: z.string(),
  treasury_account_id: z.number().nullable(),
  target_account_id: z.number().nullable(),
  branch_id: z.number(),
  transaction_date: z.string(),
  status: z.string(),
  version: z.number(),
  notes: z.string(),
  source_type: z.string().nullable(),
  source_id: z.number().nullable(),
  reversal_id: z.number().nullable(),
  allocations: z
    .array(
      z.object({
        type: z.string(),
        id: z.number(),
        amount: z.number(),
        before: z.number(),
        after: z.number(),
      }),
    )
    .optional(),
  audit: z.array(audit).optional(),
  attachments: z.array(attachment).optional(),
  journal: z
    .array(
      z.object({
        id: z.number(),
        number: z.string(),
        debit: z.string(),
        credit: z.string(),
        amount: z.number(),
      }),
    )
    .optional(),
  payload: z.record(z.unknown()).optional(),
});
export const loanSchema = z.object({
  id: z.number(),
  number: z.string(),
  direction: z.string(),
  party_name: z.string(),
  branch_id: z.number(),
  principal: z.number(),
  interest: z.number(),
  fees: z.number(),
  upfront_fee: z.number(),
  received_amount: z.number(),
  remaining_principal: z.number(),
  remaining_interest: z.number(),
  remaining_fees: z.number(),
  remaining_total: z.number(),
  progress: z.number(),
  instalments: z.number(),
  next_due: z.string().nullable(),
  next_amount: z.number(),
  overdue: z.number(),
  treasury_account_id: z.number(),
  first_due: z.string(),
  starts_on: z.string(),
  status: z.string(),
  version: z.number(),
  notes: z.string(),
  schedule: z
    .array(
      z.object({
        number: z.number(),
        due_date: z.string(),
        principal: z.number(),
        interest: z.number(),
        fees: z.number(),
        total: z.number(),
        remaining: z.number(),
        status: z.string(),
      }),
    )
    .optional(),
  salary_deductions: z.array(z.object({ payroll_item_id: z.number(), amount: z.number() })).optional(),
  payments: z
    .array(
      z.object({
        voucher_id: z.number(),
        principal: z.number(),
        interest: z.number(),
        fees: z.number(),
        status: z.string(),
        date: z.string(),
      }),
    )
    .optional(),
  audit: z.array(audit).optional(),
  attachments: z.array(attachment).optional(),
  past_schedules: z.array(z.number()).optional(),
  pending_vouchers: z
    .array(z.object({ id: z.number(), number: z.string(), category: z.string(), amount: z.number() }))
    .optional(),
  schedule_history: z
    .array(
      z.object({
        version: z.number(),
        rows: z.array(
          z.object({
            number: z.number(),
            due_date: z.string(),
            principal: z.number(),
            interest: z.number(),
            fees: z.number(),
          }),
        ),
      }),
    )
    .optional(),
});
export type FinanceVoucher = z.infer<typeof voucherSchema>;
export type FinanceLoan = z.infer<typeof loanSchema>;
export type FinanceAccount = z.infer<typeof accountSchema>;
const metaSchema = z.object({
  financial_control_available: z.boolean().optional(),
  cash_shifts_available: z.boolean().optional(),
  capabilities: z.record(z.boolean()),
  policy: z.record(z.union([z.boolean(), z.number()])),
  categories: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      kind: z.string(),
      party_type: z.string(),
      activity: z.string(),
      help: z.string(),
    }),
  ),
  accounts: z.array(accountSchema),
  branches: z.array(option),
  asset_categories: z.array(option),
  expenses: z.unknown(),
});
export type FinanceMeta = z.infer<typeof metaSchema>;
const page = <T extends z.ZodTypeAny>(row: T) =>
  z.object({
    items: z.array(row),
    total: z.number(),
    page: z.number(),
    page_size: z.number(),
    stats: z.record(z.number()),
  });
const envelope = <T extends z.ZodTypeAny>(schema: T) =>
  z.object({ success: z.literal(true), data: schema }).transform((r) => r.data);
type Query = Record<string, string | number | boolean>;
const get = <T>(path: string, schema: z.ZodType<T>, query?: Query) =>
  finoraCall({ method: "GET", path: `/api/finance/${path}`, query }, envelope(schema));
const run = <T>(
  operation: string,
  payload: Record<string, unknown>,
  schema: z.ZodType<T>,
  key: string = crypto.randomUUID(),
) =>
  finoraCall(
    { method: "POST", path: "/api/finance/commands", body: { ...payload, operation, idempotency_key: key } },
    envelope(schema),
  );
export const finance = {
  exportVouchers: (query: Query) =>
    get("vouchers/export/content", z.object({ filename: z.string(), content: z.string() }), query),
  printReport: (
    report:
      | "trial-balance"
      | "profit-loss"
      | "balance-sheet"
      | "cash-flow"
      | "customer-aging"
      | "supplier-aging"
      | "instalments"
      | "employee-advances"
      | "reconciliation-differences",
    from: string,
    to: string,
  ) =>
    desktopBridge().print.open({
      kind: "finance_report",
      report,
      ...(from ? { date_from: from } : {}),
      ...(to ? { date_to: to } : {}),
    }),
  cashFlow: (query: Query) =>
    get(
      "reports/cash-flow",
      z.object({
        activities: z.record(z.object({ in: z.number(), out: z.number(), net: z.number() })),
        net: z.number(),
      }),
      query,
    ),
  operationalReport: (name: string, query: Query) =>
    get(
      `reports/${name}`,
      z.object({
        rows: z.array(
          z.object({
            id: z.string(),
            name: z.string(),
            reference: z.string(),
            date: z.string(),
            age: z.number(),
            amount: z.number(),
            status: z.string(),
            source_type: z.string(),
            source_id: z.number().nullable(),
          }),
        ),
        total: z.number(),
        title: z.string(),
        as_of: z.string(),
        note: z.string(),
      }),
      query,
    ),
  upload: async (kind: "voucher" | "loan", id: number, file: File) => {
    if (!["application/pdf", "image/png", "image/jpeg"].includes(file.type) || file.size > 8 * 1024 * 1024)
      throw Error("اختر PDF أو PNG أو JPEG بحجم لا يتجاوز 8 ميغابايت");
    return finoraForm(
      {
        path: `/api/finance/attachments/${kind}/${id}`,
        fields: [],
        file: {
          field: "file",
          name: file.name,
          type: file.type as "application/pdf" | "image/png" | "image/jpeg",
          data: new Uint8Array(await file.arrayBuffer()),
        },
      },
      envelope(attachment),
    );
  },
  attachment: (id: number) =>
    get(
      `attachments/${id}/content`,
      z.object({ filename: z.string(), mime: z.string(), content: z.string() }),
    ),
  meta: () => get("meta", metaSchema),
  vouchers: (query: Query) => get("vouchers", page(voucherSchema), query),
  loans: (query: Query) => get("loans", page(loanSchema), query),
  voucher: (id: number) => get(`vouchers/${id}`, voucherSchema),
  loan: (id: number) => get(`loans/${id}`, loanSchema),
  parties: (type: string, q = "") => get("parties", z.object({ items: z.array(option) }), { type, q }),
  party: (type: string, id: number) =>
    get(
      `parties/${type}/${id}`,
      z.object({
        name: z.string().optional(),
        movements: z.array(voucherSchema).optional(),
        credit: z.number(),
        debt: z.number(),
        invoices: z.array(
          z.object({ id: z.number(), number: z.string(), remaining: z.number(), type: z.string() }),
        ),
      }),
    ),
  voucherCommand: (operation: string, payload: Record<string, unknown>, key?: string) =>
    run(operation, payload, voucherSchema, key),
  loanCommand: (operation: string, payload: Record<string, unknown>, key?: string) =>
    run(operation, payload, loanSchema, key),
  command: (operation: string, payload: Record<string, unknown>, key?: string) =>
    run(operation, payload, z.unknown(), key),
  trial: (query: Query) =>
    get(
      "reports/trial-balance",
      z.object({
        rows: z.array(
          z.object({
            id: z.number(),
            code: z.string(),
            name: z.string(),
            type: z.string(),
            debit: z.number(),
            credit: z.number(),
            balance: z.number(),
          }),
        ),
        debit: z.number(),
        credit: z.number(),
        profit: z.number(),
        assets: z.number(),
        liabilities: z.number(),
        equity: z.number(),
        revenue: z.number(),
        expenses: z.number(),
        balanced: z.boolean(),
        opening_migration_complete: z.boolean(),
      }),
      query,
    ),
  journal: (query: Query) =>
    get(
      "journal",
      z.object({
        total: z.number(),
        rows: z.array(
          z.object({
            id: z.number(),
            number: z.string(),
            date: z.string(),
            description: z.string(),
            debit: z.string(),
            credit: z.string(),
            amount: z.number(),
          }),
        ),
      }),
      query,
    ),
  ledger: (id: number) =>
    get(
      `accounts/${id}/ledger`,
      z.object({
        id: z.number(),
        name: z.string(),
        balance: z.number(),
        movements: z.array(
          z.object({
            key: z.string(),
            date: z.string(),
            amount: z.number(),
            note: z.string(),
            balance_after: z.number(),
          }),
        ),
      }),
    ),
  settings: () =>
    get(
      "settings",
      z.object({
        policy: z.record(z.union([z.boolean(), z.number()])),
        mappings: z.array(
          z.object({ key: z.string(), account_id: z.number(), name: z.string(), type: z.string() }),
        ),
        chart: z.array(option.extend({ code: z.string(), type: z.string() })),
      }),
    ),
  migration: () =>
    get(
      "migration/preview",
      z.object({
        hash: z.string(),
        issues: z.array(z.string()).optional(),
        complete: z.boolean(),
        debt_upgrade_required: z.boolean().optional().default(false),
        rows: z.array(
          z.object({
            key: z.string(),
            name: z.string(),
            current: z.number(),
            target: z.number(),
            difference: z.number(),
          }),
        ),
      }),
    ),
  reconciliations: () =>
    get(
      "reconciliations",
      z.object({
        items: z.array(
          z.object({
            id: z.number(),
            treasury_account_id: z.number(),
            starts_on: z.string(),
            ends_on: z.string(),
            candidates: z
              .array(z.object({ key: z.string(), date: z.string(), amount: z.number(), note: z.string() }))
              .default([]),
            difference: z.number(),
            status: z.string(),
            lines: z.array(
              z.object({
                id: z.number(),
                date: z.string(),
                amount: z.number(),
                reference: z.string(),
                ledger_key: z.string().nullable(),
              }),
            ),
          }),
        ),
      }),
    ),
  notices: () =>
    get(
      "notifications",
      z.object({
        items: z.array(
          z.object({
            type: z.string(),
            source_type: z.string(),
            source_id: z.number(),
            title: z.string(),
            amount: z.number(),
            date: z.string().optional(),
          }),
        ),
      }),
    ),
  print: (kind: "finance_voucher" | "finance_loan" | "finance_cash_shift", id: number) =>
    desktopBridge().print.open({ kind, id }),
};
