/**
 * Reports — FINORA modules/reports_api (services/reports_service.py). Every
 * number is computed on the server by one shared engine; the desktop only
 * renders it. Filters travel with every call so drill-down keeps them.
 */
import { z } from "zod";
import { desktopBridge } from "@/services/bridge";
import type { ReportExportResult, ReportQuery, ReportSection } from "@shared/ipc";
import { REPORT_SECTIONS } from "@shared/ipc";
import { finoraCall } from "./transport";

export { REPORT_SECTIONS };
export type { ReportQuery, ReportSection };

export const REPORT_PERIODS = [
  "today",
  "yesterday",
  "this_week",
  "this_month",
  "last_month",
  "this_year",
  "custom",
] as const;
export type ReportPeriod = (typeof REPORT_PERIODS)[number];

export interface ReportFilters {
  period: ReportPeriod;
  dateFrom: string;
  dateTo: string;
  branchId: number | null;
  employeeId: number | null;
}

export function filterQuery(filters: ReportFilters): ReportQuery {
  return {
    period: filters.period,
    ...(filters.period === "custom" ? { date_from: filters.dateFrom, date_to: filters.dateTo } : {}),
    ...(filters.branchId ? { branch_id: filters.branchId } : {}),
    ...(filters.employeeId ? { employee_id: filters.employeeId } : {}),
  };
}

const money = z.number().int();
const maybeMoney = money.nullable();
const pct = z.number().nullable();
const sectionEnum = z.enum(REPORT_SECTIONS);
const appliedFilters = z.object({
  period: z.string(),
  date_from: z.string(),
  date_to: z.string(),
  branch_id: z.number().int().nullable(),
  employee_id: z.number().int().nullable(),
});
const pagination = z.object({
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
});
export type Pagination = z.infer<typeof pagination>;
const breakdownRow = z.object({ key: z.string(), label: z.string(), count: z.number().int(), amount: money });
export type BreakdownRow = z.infer<typeof breakdownRow>;

const metaSchema = z.object({
  success: z.literal(true),
  company: z.string(),
  sections: z.record(z.boolean()),
  can_export: z.boolean(),
  can_pick_branch: z.boolean(),
  branches: z.array(z.object({ id: z.number().int(), name: z.string() })),
  employees: z.array(z.object({ id: z.number().int(), name: z.string() })),
});
export type ReportsMeta = z.infer<typeof metaSchema>;

const kpiSchema = z.object({
  key: z.enum(["sales", "net_profit", "expenses", "cash", "receivables", "inventory"]),
  label: z.string(),
  value: maybeMoney,
  previous: maybeMoney,
  change_pct: pct,
  tone: z.enum(["good", "bad", "neutral"]),
  section: sectionEnum,
});
export type Kpi = z.infer<typeof kpiSchema>;

const named = z.object({ name: z.string(), amount: money });
const dashboardSchema = z.object({
  success: z.literal(true),
  filters: appliedFilters,
  comparison_range: z.object({
    previous: z.tuple([z.string(), z.string()]),
    last_year: z.tuple([z.string(), z.string()]),
  }),
  allowed: z.record(z.boolean()),
  employee_scoped: z.boolean(),
  kpis: z.array(kpiSchema),
  comparison: z.array(
    z.object({ key: z.string(), label: z.string(), current: money, previous: money, last_year: money }),
  ),
  sales_series: z.array(z.object({ key: z.string(), amount: money })),
  sections: z.object({
    sales: z
      .object({ gross: money, net: money, invoices: z.number().int(), average: money, change_pct: pct })
      .optional(),
    profit: z.object({ revenue: money, cogs: money, expenses: money, net_profit: money }).optional(),
    expenses: z
      .object({
        total: money,
        count: z.number().int(),
        top_category: breakdownRow.nullable(),
        change_pct: pct,
      })
      .optional(),
    cash: z.object({ cash_in: money, cash_out: money, balance: money, transfers: money }).optional(),
    customers: z
      .object({
        credit_sales: money,
        collections: maybeMoney,
        receivables: money,
        top_debtors: z.array(named.extend({ customer_id: z.number().int().nullable() })),
      })
      .optional(),
    purchases: z
      .object({
        total: money,
        supplier_payments: maybeMoney,
        supplier_debts: money,
        top_suppliers: z.array(
          named.extend({ supplier_id: z.number().int().nullable(), count: z.number().int() }),
        ),
      })
      .optional(),
    inventory: z
      .object({
        quantity: z.number().int(),
        value: money,
        low_stock: z.number().int(),
        stagnant: z.number().int(),
        best_seller: z.object({ name: z.string(), quantity: z.number().int() }).passthrough().nullable(),
      })
      .optional(),
    invoices: z
      .object({
        paid: z.number().int(),
        partial: z.number().int(),
        credit: z.number().int(),
        cancelled: z.number().int(),
        returned: z.number().int(),
        total: z.number().int(),
        amount: money,
      })
      .optional(),
    employees: z
      .object({
        top: z.array(
          z
            .object({
              employee_id: z.number().int().nullable(),
              name: z.string(),
              sales: money,
              collections: money,
            })
            .passthrough(),
        ),
      })
      .optional(),
    cashflow: z.object({ inflow: money, outflow: money, net: money }).optional(),
  }),
});
export type Dashboard = z.infer<typeof dashboardSchema>;

const invoiceRow = z.object({
  id: z.number().int(),
  date: z.string().nullable(),
  customer_id: z.number().int().nullable(),
  customer: z.string(),
  employee_id: z.number().int().nullable(),
  employee: z.string(),
  branch: z.string(),
  gross: money,
  discount: money,
  total: money,
  paid: money,
  remaining: money,
  sale_type: z.string(),
  status: z.string(),
  state: z.string(),
});
export type InvoiceReportRow = z.infer<typeof invoiceRow>;

const base = { success: z.literal(true), filters: appliedFilters };

const salesSchema = z.object({
  ...base,
  metrics: z.object({
    gross: money,
    net: money,
    invoices: z.number().int(),
    items: z.number().int(),
    average: money,
    discounts: money,
    returns: money,
    returns_count: z.number().int(),
    cogs: maybeMoney,
    gross_profit: maybeMoney,
    change_pct: pct,
  }),
  breakdown: z.object({ by: z.string(), rows: z.array(breakdownRow) }),
  rows: z.array(invoiceRow),
  pagination,
});
export type SalesReport = z.infer<typeof salesSchema>;

const statement = z.object({
  gross_revenue: money,
  returns: money,
  discounts: money,
  net_revenue: money,
  cogs: money,
  gross_profit: money,
  operating_expenses: money,
  depreciation: money,
  savings_fees: money,
  other_expenses: money,
  inventory_losses: money.optional().default(0),
  net_profit: money,
});
const profitSchema = z.object({
  ...base,
  statement,
  previous: statement,
  margins: z.object({ gross_margin_pct: pct, net_margin_pct: pct }),
  change_pct: z.object({ net_revenue: pct, gross_profit: pct, net_profit: pct }),
  trend: z.array(z.object({ key: z.string(), revenue: money, net_profit: money })),
});
export type ProfitReport = z.infer<typeof profitSchema>;

const expensesSchema = z.object({
  ...base,
  metrics: z.object({ total: money, count: z.number().int(), change_pct: pct }),
  breakdown: z.object({ by: z.string(), rows: z.array(breakdownRow) }),
  rows: z.array(
    z.object({
      id: z.number().int(),
      date: z.string().nullable(),
      category: z.string(),
      description: z.string(),
      amount: money,
      employee: z.string(),
      branch: z.string(),
      account: z.string(),
      payment_method: z.string(),
    }),
  ),
  pagination,
});
export type ExpensesReport = z.infer<typeof expensesSchema>;

const cashSchema = z.object({
  ...base,
  metrics: z.object({ cash_in: money, cash_out: money, opening: money, closing: money, transfers: money }),
  accounts: z.array(
    z
      .object({
        id: z.number().int(),
        name: z.string(),
        type: z.string().nullable(),
        is_cash: z.boolean(),
        opening: money,
        cash_in: money,
        cash_out: money,
        closing: money,
        last_movement: z.string().nullable(),
      })
      .passthrough(),
  ),
  rows: z.array(
    z.object({
      date: z.string(),
      account: z.string(),
      type: z.string(),
      reason: z.string(),
      reference: z.string(),
      invoice_id: z.number().int().nullable().optional(),
      description: z.string(),
      cash_in: money,
      cash_out: money,
      balance: z.number().nullable().optional(),
      is_transfer: z.boolean(),
    }),
  ),
  pagination,
  transfers: z.array(
    z.object({
      id: z.number().int(),
      date: z.string().nullable(),
      from: z.string(),
      to: z.string(),
      amount: money,
      note: z.string(),
    }),
  ),
});
export type CashReport = z.infer<typeof cashSchema>;

const customersSchema = z.object({
  ...base,
  tab: z.enum(["customers", "debts"]),
  metrics: z.object({
    credit_sales: money,
    collections: maybeMoney,
    receivables: money,
    due_today: money,
    overdue: money,
    not_due: money,
    open_invoices: z.number().int(),
  }),
  aging: z.array(z.object({ key: z.string(), label: z.string(), amount: money })),
  rows: z.array(
    z.union([
      z.object({
        invoice_id: z.number().int(),
        customer_id: z.number().int().nullable(),
        customer: z.string(),
        phone: z.string(),
        total: money,
        paid: money,
        remaining: money,
        due_date: z.string(),
        days_overdue: z.number().int(),
        bucket: z.string(),
      }),
      z.object({
        customer_id: z.number().int().nullable(),
        name: z.string(),
        phone: z.string(),
        orders: z.number().int(),
        purchases: money,
        paid: money,
        debt: money,
        last_purchase: z.string().nullable(),
      }),
    ]),
  ),
  pagination,
});
export type CustomersReport = z.infer<typeof customersSchema>;

const purchasesSchema = z.object({
  ...base,
  tab: z.enum(["purchases", "suppliers", "debts"]),
  metrics: z.object({
    count: z.number().int(),
    amount: money,
    paid: money,
    remaining: money,
    quantity: z.number().int(),
    supplier_debts: money,
  }),
  by_supplier: z.array(
    z.object({
      supplier_id: z.number().int().nullable(),
      name: z.string(),
      count: z.number().int(),
      amount: money,
    }),
  ),
  rows: z.array(
    z.union([
      z.object({
        purchase_id: z.number().int(),
        invoice_no: z.string(),
        date: z.string().nullable(),
        supplier_id: z.number().int().nullable(),
        supplier: z.string(),
        amount: money,
        paid: money,
        remaining: money,
        status: z.string(),
      }),
      z.object({
        supplier_id: z.number().int(),
        name: z.string(),
        phone: z.string(),
        purchases: money,
        invoices: z.number().int(),
        total_paid: money,
        balance: money,
        last_purchase: z.string().nullable(),
      }),
    ]),
  ),
  pagination,
});
export type PurchasesReport = z.infer<typeof purchasesSchema>;

const bucketStat = z.object({ count: z.number().int(), value: money });
const inventorySchema = z.object({
  ...base,
  tab: z.enum(["stock", "low", "stagnant", "movements"]),
  metrics: z.object({
    quantity: z.number().int(),
    value: money,
    low_stock: z.number().int(),
    stagnant: z.number().int(),
    stagnant_value: money,
    stagnant_buckets: z.record(bucketStat),
    movement_types: z.array(z.object({ type: z.string(), quantity: z.number().int() })).optional(),
  }),
  best_sellers: z.array(
    z.object({
      product_id: z.number().int().nullable(),
      name: z.string(),
      quantity: z.number().int(),
      revenue: money,
    }),
  ),
  rows: z.array(z.record(z.union([z.string(), z.number(), z.null()]))),
  pagination,
});
export type InventoryReport = z.infer<typeof inventorySchema>;

const invoicesSchema = z.object({
  ...base,
  state: z.string(),
  metrics: z.object({
    paid: z.number().int(),
    partial: z.number().int(),
    credit: z.number().int(),
    cancelled: z.number().int(),
    returned: z.number().int(),
    total: z.number().int(),
    amount: money,
    outstanding: money,
  }),
  rows: z.array(invoiceRow),
  pagination,
});
export type InvoicesReport = z.infer<typeof invoicesSchema>;

const employeeRow = z.object({
  employee_id: z.number().int().nullable(),
  name: z.string(),
  orders: z.number().int(),
  sales: money,
  average: money,
  collections: money,
  discounts: money,
  returns: money,
  profit: maybeMoney,
  commission: money,
});
export type EmployeeReportRow = z.infer<typeof employeeRow>;
const employeesSchema = z.object({
  ...base,
  sort: z.string(),
  show_profit: z.boolean(),
  rows: z.array(employeeRow),
  totals: z.record(money),
});
export type EmployeesReport = z.infer<typeof employeesSchema>;

const flowLine = z.object({ key: z.string(), label: z.string(), amount: money });
const cashflowSchema = z.object({
  ...base,
  flow: z.object({
    opening: money,
    inflow: money,
    outflow: money,
    net: money,
    net_transfers: money,
    closing: money,
    inflows: z.array(flowLine),
    outflows: z.array(flowLine),
  }),
  grain: z.string(),
  series: z.array(z.object({ key: z.string(), inflow: money, outflow: money, net: money })),
});
export type CashflowReport = z.infer<typeof cashflowSchema>;

const amountLine = z.object({ key: z.string(), label: z.string(), amount: money });
const equitySchema = z.object({
  ...base,
  position: z.object({
    assets: z.array(amountLine),
    liabilities: z.array(amountLine),
    total_assets: money,
    total_liabilities: money,
    equity: money,
    balanced: z.boolean(),
    note: z.string(),
  }),
  profit: z.object({
    net_revenue: money,
    cogs: money,
    gross_profit: money,
    operating_expenses: money,
    other_expenses: money,
    net_profit: money,
  }),
  bridge: z.array(amountLine),
  cash: z.object({ opening: money, net_change: money, closing: money }),
  went_to: z.record(money),
  summary: z.array(z.string()),
});
export type EquityReport = z.infer<typeof equitySchema>;

export interface SectionReports {
  sales: SalesReport;
  profit: ProfitReport;
  expenses: ExpensesReport;
  cash: CashReport;
  customers: CustomersReport;
  purchases: PurchasesReport;
  inventory: InventoryReport;
  invoices: InvoicesReport;
  employees: EmployeesReport;
  cashflow: CashflowReport;
  equity: EquityReport;
}

const SECTION_SCHEMAS: { [K in ReportSection]: z.ZodType<SectionReports[K], z.ZodTypeDef, unknown> } = {
  sales: salesSchema,
  profit: profitSchema,
  expenses: expensesSchema,
  cash: cashSchema,
  customers: customersSchema,
  purchases: purchasesSchema,
  inventory: inventorySchema,
  invoices: invoicesSchema,
  employees: employeesSchema,
  cashflow: cashflowSchema,
  equity: equitySchema,
};

/** Section-specific view options (tab, grouping, sort…) plus paging. */
export type SectionOptions = Partial<
  Pick<ReportQuery, "tab" | "state" | "by" | "sort" | "grain" | "search">
> & {
  page?: number;
  pageSize?: number;
};

export const reports = {
  meta(): Promise<ReportsMeta> {
    return finoraCall({ method: "GET", path: "/reports/api/v2/meta" }, metaSchema);
  },
  dashboard(filters: ReportFilters, grain: "day" | "month" | "year"): Promise<Dashboard> {
    return finoraCall(
      {
        method: "GET",
        path: "/reports/api/v2/dashboard",
        query: { ...filterQuery(filters), grain },
        timeoutMs: 60_000,
      },
      dashboardSchema,
    );
  },
  section<K extends ReportSection>(
    section: K,
    filters: ReportFilters,
    options: SectionOptions = {},
  ): Promise<SectionReports[K]> {
    const { page, pageSize, ...view } = options;
    const query: Record<string, string | number> = { ...filterQuery(filters) };
    for (const [key, value] of Object.entries(view)) if (value) query[key] = value;
    if (page) query.page = page;
    if (pageSize) query.page_size = pageSize;
    return finoraCall(
      { method: "GET", path: `/reports/api/v2/section/${section}`, query, timeoutMs: 60_000 },
      SECTION_SCHEMAS[section],
    );
  },
  export(
    section: ReportSection,
    format: "print" | "pdf" | "xlsx",
    title: string,
    filters: ReportFilters,
    view: SectionOptions = {},
  ): Promise<ReportExportResult> {
    const query: ReportQuery = { ...filterQuery(filters) };
    const keys = ["tab", "state", "by", "sort", "grain", "search"] as const;
    for (const key of keys) {
      const value = view[key];
      if (value) query[key] = value;
    }
    return desktopBridge().reports.export({ section, format, title, query });
  },
};

/** FINORA web pages a report row links to (allow-listed in main). */
export function openReportEntity(
  kind: "invoice" | "customer" | "supplier" | "product" | "employee",
  id: number,
): Promise<void> {
  const path = {
    invoice: `/orders/${id}`,
    customer: `/customers/orders/${id}`,
    supplier: `/suppliers/${id}`,
    product: `/inventory/report/${id}`,
    employee: `/employees/view-orders/${id}`,
  }[kind];
  return desktopBridge().app.openInFinora(path);
}
