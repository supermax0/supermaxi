import { z } from "zod";
import { finoraCall } from "./transport";

/** FINORA expenses (routes/expenses.py) — the same rules as the web page: due items are posted to the
 *  treasury immediately, future ones stay scheduled, deleting a posted expense refunds the treasury. */
export const EXPENSE_TABS = ["all", "posted", "scheduled"] as const;
export type ExpenseTab = (typeof EXPENSE_TABS)[number];

const categorySchema = z.object({
  key: z.string(),
  label: z.string(),
  icon: z.string().nullable().optional(),
  builtin: z.boolean().optional(),
});
export type ExpenseCategory = z.infer<typeof categorySchema>;

const accountSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  type: z.string(),
  is_default: z.boolean(),
  branch_name: z.string().nullable().optional(),
});
export type TreasuryChoice = z.infer<typeof accountSchema>;

const metaSchema = z.object({
  success: z.literal(true),
  categories: z.array(categorySchema),
  treasury_accounts: z.array(accountSchema),
  today: z.string(),
});
export type ExpensesMeta = z.infer<typeof metaSchema>;

export const expenseRowSchema = z.object({
  id: z.number().int(),
  title: z.string(),
  category: z.string().nullable(),
  category_key: z.string(),
  category_label: z.string(),
  category_icon: z.string(),
  amount: z.number(),
  note: z.string(),
  base_note: z.string(),
  expense_date: z.string().nullable(),
  post_time: z.string(),
  treasury_account_id: z.number().int().nullable(),
  treasury_account_name: z.string(),
  cash_posted: z.boolean(),
  status: z.enum(["posted", "scheduled"]),
  repeat_index: z.number().int().nullable(),
  repeat_total: z.number().int().nullable(),
  repeat_series_id: z.string().nullable(),
  is_payroll: z.boolean(),
  created_at: z.string(),
});
export type ExpenseRow = z.infer<typeof expenseRowSchema>;

const pageSchema = z.object({
  success: z.literal(true),
  rows: z.array(expenseRowSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
  counts: z.object({ all: z.number().int(), posted: z.number().int(), scheduled: z.number().int() }),
  summary: z.object({
    today_total: z.number(),
    month_total: z.number(),
    year_total: z.number(),
    scheduled_total: z.number(),
    scheduled_count: z.number().int(),
    filtered_total: z.number(),
  }),
  by_category: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      icon: z.string(),
      amount: z.number(),
      count: z.number().int(),
    }),
  ),
});
export type ExpensesPage = z.infer<typeof pageSchema>;

export interface ExpensesQuery {
  tab: ExpenseTab;
  search: string;
  category: string;
  treasuryAccountId: number | null;
  dateFrom: string;
  dateTo: string;
  sort: "date" | "oldest" | "amount";
  page: number;
  pageSize: number;
}

export interface ExpenseInput {
  title: string;
  category: string;
  amount: number;
  expense_date: string;
  expense_time: string;
  treasury_account_id: number | null;
  note: string;
  repeat_enabled: boolean;
  repeat_interval: number;
  repeat_unit: "days" | "weeks" | "months" | "years";
  repeat_count: number;
}

const createdSchema = z.object({
  success: z.literal(true),
  message: z.string(),
  ids: z.array(z.number().int()),
  count: z.number().int(),
  posted_count: z.number().int(),
  scheduled_count: z.number().int(),
  amount_withdrawn: z.number(),
});

export const expenses = {
  meta() {
    return finoraCall({ method: "GET", path: "/expenses/api/meta" }, metaSchema);
  },
  list(q: ExpensesQuery) {
    return finoraCall(
      {
        method: "GET",
        path: "/expenses/api/page",
        query: {
          tab: q.tab,
          search: q.search.trim(),
          category: q.category,
          treasury_account_id: q.treasuryAccountId ?? "",
          date_from: q.dateFrom,
          date_to: q.dateTo,
          sort: q.sort,
          page: q.page,
          page_size: q.pageSize,
        },
      },
      pageSchema,
    );
  },
  create(input: ExpenseInput) {
    return finoraCall(
      {
        method: "POST",
        path: "/expenses/api/create",
        body: { ...input, treasury_account_id: input.treasury_account_id ?? "", title: input.title.trim() },
        timeoutMs: 30_000,
      },
      createdSchema,
    );
  },
  remove(id: number) {
    return finoraCall(
      { method: "POST", path: `/expenses/delete/${id}` },
      z.object({ success: z.literal(true), message: z.string().optional() }),
    );
  },
  addCategory(name: string, icon: string) {
    return finoraCall(
      { method: "POST", path: "/expenses/categories/add", body: { name: name.trim(), icon } },
      z.object({ success: z.literal(true), category: categorySchema }),
    );
  },
};
