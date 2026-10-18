import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowRight, Equal, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { finora, toFinoraError } from "@/api/finora";
import {
  openReportEntity,
  type BreakdownRow,
  type CashflowReport,
  type CashReport,
  type CustomersReport,
  type EmployeesReport,
  type ExpensesReport,
  type InventoryReport,
  type InvoiceReportRow,
  type InvoicesReport,
  type Pagination,
  type ProfitReport,
  type PurchasesReport,
  type ReportFilters,
  type ReportSection,
  type SalesReport,
  type SectionOptions,
  type SectionReports,
} from "@/api/finora/reports";
import { TablePagination } from "@/components/TablePagination";
import { bucketLabel, PAYMENT_LABELS, SECTION_INFO } from "@/features/reports/labels";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { BarChart, LineChart } from "./charts";
import { Change, Money } from "./ReportsDashboard";

/* ---------------------------------------------------------- building blocks */

interface Metric {
  label: string;
  value: number | null | undefined;
  money?: boolean;
  tone?: "good" | "bad" | "warn";
  suffix?: string;
}

function Metrics({ items }: { items: Metric[] }) {
  return (
    <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-5">
      {items.map((m) => (
        <div key={m.label} className="rounded-panel bg-white px-4 py-3 shadow-control ring-1 ring-line/60">
          <p className="truncate text-xs text-ink-soft">{m.label}</p>
          <p
            className={cn(
              "mt-1 text-[18px] font-bold",
              m.tone === "good"
                ? "text-success"
                : m.tone === "bad"
                  ? "text-danger"
                  : m.tone === "warn"
                    ? "text-warning"
                    : "text-ink",
            )}
          >
            {m.money ? (
              <Money value={m.value ?? null} />
            ) : m.value === null || m.value === undefined ? (
              "—"
            ) : (
              <span className="ltr-isolate">
                {formatNumber(m.value)}
                {m.suffix ?? ""}
              </span>
            )}
          </p>
        </div>
      ))}
    </div>
  );
}

function Panel({
  title,
  children,
  actions,
  className,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={title}
      className={cn("min-w-0 rounded-panel bg-white p-4 shadow-control ring-1 ring-line/60", className)}
    >
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-[15px] font-bold text-ink">{title}</h3>
        <div className="ms-auto flex flex-wrap items-center gap-2">{actions}</div>
      </header>
      {children}
    </section>
  );
}

function Pills<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: Array<[T, string]>;
  onChange(v: T): void;
  label: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="flex flex-wrap gap-0.5 rounded-control bg-surface-sunken p-0.5"
    >
      {options.map(([id, text]) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={value === id}
          onClick={() => onChange(id)}
          className={cn(
            "h-8 rounded-[9px] px-3 text-xs font-semibold transition-colors",
            value === id ? "bg-white text-violet-deep shadow-control" : "text-ink-soft hover:bg-white/70",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function Bars({ rows, empty = "لا توجد بيانات" }: { rows: BreakdownRow[]; empty?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.amount));
  if (rows.length === 0) return <p className="py-6 text-center text-sm text-ink-faint">{empty}</p>;
  return (
    <ul className="max-h-[320px] space-y-2 overflow-y-auto pe-1">
      {rows.map((row) => (
        <li key={row.key || row.label} className="text-[13px]">
          <div className="mb-1 flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate text-ink">{row.label}</span>
            <span className="text-xs text-ink-faint">{formatNumber(row.count)}</span>
            <Money value={row.amount} className="font-semibold text-ink" />
          </div>
          <div className="h-1.5 rounded-full bg-surface-sunken">
            <div
              className="h-full rounded-full bg-violet/70"
              style={{ width: `${(Math.max(0, row.amount) / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export interface Column<T> {
  id: string;
  header: string;
  cell(row: T): ReactNode;
  money?: boolean;
}

function EntityLink({
  kind,
  id,
  children,
}: {
  kind: Parameters<typeof openReportEntity>[0];
  id: number | null | undefined;
  children: ReactNode;
}) {
  if (!id) return <>{children}</>;
  return (
    <button
      type="button"
      onClick={() => {
        openReportEntity(kind, id).catch((error: unknown) => toast.error(toFinoraError(error).message));
      }}
      className="font-semibold text-azure underline-offset-2 hover:underline"
    >
      {children}
    </button>
  );
}

function Table<T>({
  label,
  columns,
  rows,
  pagination,
  onPage,
  rowKey,
  footer,
}: {
  label: string;
  columns: Array<Column<T>>;
  rows: T[];
  pagination?: Pagination;
  onPage?(page: number, size: number): void;
  rowKey(row: T, index: number): string;
  footer?: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="overflow-x-auto rounded-control ring-1 ring-line/60">
        <table aria-label={label} className="w-full min-w-[720px] text-[13px]">
          <thead className="sticky top-0 bg-surface-sunken text-ink-soft">
            <tr>
              {columns.map((c) => (
                <th key={c.id} scope="col" className="whitespace-nowrap px-3 py-2 text-start font-semibold">
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={rowKey(row, i)} className="border-t border-line/50 odd:bg-white even:bg-[#fbfaff]">
                {columns.map((c) => (
                  <td key={c.id} className="whitespace-nowrap px-3 py-2 text-ink">
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-8 text-center text-ink-faint">
                  لا توجد بيانات لهذه الفلاتر
                </td>
              </tr>
            )}
          </tbody>
          {footer && <tfoot className="border-t-2 border-line bg-violet-soft/40 font-bold">{footer}</tfoot>}
        </table>
      </div>
      {pagination && onPage && pagination.total > 0 && (
        <TablePagination
          page={pagination.page}
          totalPages={pagination.total_pages}
          total={pagination.total}
          pageSize={pagination.page_size}
          noun="سجل"
          onPage={(page) => onPage(page, pagination.page_size)}
          onPageSize={(size) => onPage(1, size)}
        />
      )}
    </div>
  );
}

const STATE_TONES: Record<string, string> = {
  مدفوعة: "bg-success-soft text-success",
  جزئية: "bg-azure-soft text-azure",
  آجلة: "bg-warning-soft text-warning",
  ملغاة: "bg-danger-soft text-danger",
  مرتجعة: "bg-surface-sunken text-ink-soft",
};

function StateBadge({ state }: { state: string }) {
  return (
    <span
      className={cn(
        "rounded-full px-2.5 py-0.5 text-xs font-semibold",
        STATE_TONES[state] ?? "bg-surface-sunken text-ink-soft",
      )}
    >
      {state}
    </span>
  );
}

const money = (value: number) => <Money value={value} />;

function invoiceColumns(withPayment: boolean): Array<Column<InvoiceReportRow>> {
  return [
    {
      id: "date",
      header: "التاريخ",
      cell: (r) => <span className="ltr-isolate text-ink-soft">{r.date ?? "—"}</span>,
    },
    {
      id: "id",
      header: "رقم الفاتورة",
      cell: (r) => (
        <EntityLink kind="invoice" id={r.id}>
          <span className="ltr-isolate">#{r.id}</span>
        </EntityLink>
      ),
    },
    {
      id: "customer",
      header: "العميل",
      cell: (r) => (
        <EntityLink kind="customer" id={r.customer_id}>
          {r.customer || "—"}
        </EntityLink>
      ),
    },
    {
      id: "employee",
      header: "الموظف",
      cell: (r) => (
        <EntityLink kind="employee" id={r.employee_id}>
          {r.employee || "—"}
        </EntityLink>
      ),
    },
    ...(withPayment
      ? [
          {
            id: "payment",
            header: "طريقة الدفع",
            cell: (r: InvoiceReportRow) => PAYMENT_LABELS[r.sale_type] ?? (r.sale_type || "—"),
          },
        ]
      : [{ id: "branch", header: "الفرع", cell: (r: InvoiceReportRow) => r.branch || "—" }]),
    { id: "gross", header: "الإجمالي", cell: (r) => money(r.gross), money: true },
    { id: "discount", header: "الخصم", cell: (r) => money(r.discount), money: true },
    { id: "total", header: "الصافي", cell: (r) => money(r.total), money: true },
    { id: "paid", header: "المدفوع", cell: (r) => money(r.paid), money: true },
    {
      id: "remaining",
      header: "المتبقي",
      cell: (r) => <Money value={r.remaining} className={r.remaining > 0 ? "text-warning" : ""} />,
      money: true,
    },
    { id: "state", header: "الحالة", cell: (r) => <StateBadge state={r.state} /> },
  ];
}

/* ------------------------------------------------------------ section views */

interface ViewProps<K extends ReportSection> {
  data: SectionReports[K];
  options: SectionOptions;
  setOptions(patch: SectionOptions): void;
}

function SalesView({ data, options, setOptions }: ViewProps<"sales">) {
  const m = data.metrics;
  return (
    <>
      <Metrics
        items={[
          { label: "إجمالي المبيعات", value: m.gross, money: true },
          { label: "صافي المبيعات", value: m.net, money: true },
          { label: "عدد الفواتير", value: m.invoices },
          { label: "المنتجات المباعة", value: m.items },
          { label: "متوسط الفاتورة", value: m.average, money: true },
          { label: "الخصومات", value: m.discounts, money: true, tone: "warn" },
          { label: "المرتجعات", value: m.returns, money: true, tone: "bad" },
          { label: "تكلفة البضاعة المباعة", value: m.cogs, money: true },
          { label: "إجمالي الربح", value: m.gross_profit, money: true, tone: "good" },
        ]}
      />
      <Panel
        title="المبيعات حسب"
        actions={
          <>
            <Change
              pct={m.change_pct}
              tone={m.change_pct === null ? "neutral" : m.change_pct >= 0 ? "good" : "bad"}
            />
            <Pills
              label="تجميع المبيعات"
              value={options.by ?? "day"}
              onChange={(by) => setOptions({ by, page: 1 })}
              options={[
                ["day", "اليوم"],
                ["week", "الأسبوع"],
                ["month", "الشهر"],
                ["product", "المنتج"],
                ["category", "التصنيف"],
                ["employee", "الموظف"],
                ["branch", "الفرع"],
                ["customer", "العميل"],
                ["payment", "طريقة الدفع"],
              ]}
            />
          </>
        }
      >
        {["day", "week", "month"].includes(options.by ?? "day") ? (
          <LineChart
            label="المبيعات حسب الفترة"
            points={data.breakdown.rows.map((r) => ({
              key: r.key,
              label: bucketLabel(r.label),
              value: r.amount,
            }))}
          />
        ) : (
          <Bars rows={data.breakdown.rows} />
        )}
      </Panel>
      <Panel title="الفواتير">
        <Table
          label="فواتير المبيعات"
          columns={invoiceColumns(false)}
          rows={data.rows}
          rowKey={(r) => String(r.id)}
          pagination={data.pagination}
          onPage={(page, pageSize) => setOptions({ page, pageSize })}
        />
      </Panel>
    </>
  );
}

function ProfitView({ data, options, setOptions }: ViewProps<"profit">) {
  const st = data.statement;
  const prev = data.previous;
  const lines: Array<{
    label: string;
    value: number;
    prev: number;
    sign: "plus" | "minus" | "eq";
    strong?: boolean;
  }> = [
    { label: "الإيرادات", value: st.gross_revenue, prev: prev.gross_revenue, sign: "plus" },
    { label: "المرتجعات", value: st.returns, prev: prev.returns, sign: "minus" },
    { label: "الخصومات", value: st.discounts, prev: prev.discounts, sign: "minus" },
    { label: "صافي الإيرادات", value: st.net_revenue, prev: prev.net_revenue, sign: "eq", strong: true },
    { label: "تكلفة البضاعة المباعة", value: st.cogs, prev: prev.cogs, sign: "minus" },
    { label: "إجمالي الربح", value: st.gross_profit, prev: prev.gross_profit, sign: "eq", strong: true },
    {
      label: "المصاريف التشغيلية",
      value: st.operating_expenses,
      prev: prev.operating_expenses,
      sign: "minus",
    },
    ...(st.inventory_losses !== 0 || prev.inventory_losses !== 0
      ? [
          {
            label: "صافي خسائر المخزون / العكس",
            value: st.inventory_losses,
            prev: prev.inventory_losses,
            sign: "minus" as const,
          },
        ]
      : []),
    {
      label: "الاستهلاك ومصاريف أخرى",
      value: st.other_expenses - st.inventory_losses,
      prev: prev.other_expenses - prev.inventory_losses,
      sign: "minus",
    },
    { label: "صافي الربح", value: st.net_profit, prev: prev.net_profit, sign: "eq", strong: true },
  ];
  const SignIcon = { plus: Plus, minus: Minus, eq: Equal };
  return (
    <>
      <Metrics
        items={[
          { label: "صافي الإيرادات", value: st.net_revenue, money: true },
          { label: "إجمالي الربح", value: st.gross_profit, money: true },
          {
            label: "صافي الربح",
            value: st.net_profit,
            money: true,
            tone: st.net_profit >= 0 ? "good" : "bad",
          },
          { label: "هامش الربح الإجمالي", value: data.margins.gross_margin_pct, suffix: "%" },
          { label: "هامش صافي الربح", value: data.margins.net_margin_pct, suffix: "%" },
        ]}
      />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="قائمة الدخل">
          <table aria-label="قائمة الدخل" className="w-full text-[13.5px]">
            <thead>
              <tr className="text-xs text-ink-faint">
                <th className="py-1 text-start font-medium">البند</th>
                <th className="py-1 text-start font-medium">هذه الفترة</th>
                <th className="py-1 text-start font-medium">الفترة السابقة</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => {
                const Icon = SignIcon[line.sign];
                return (
                  <tr
                    key={line.label}
                    className={cn("border-t border-line/50", line.strong && "bg-violet-soft/40 font-bold")}
                  >
                    <td className="flex items-center gap-2 px-2 py-2">
                      <Icon
                        size={13}
                        className={
                          line.sign === "minus"
                            ? "text-danger"
                            : line.sign === "plus"
                              ? "text-success"
                              : "text-ink"
                        }
                        aria-hidden
                      />
                      {line.label}
                    </td>
                    <td className="px-2 py-2">
                      <Money value={line.value} />
                    </td>
                    <td className="px-2 py-2 text-ink-soft">
                      <Money value={line.prev} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-3 text-xs leading-5 text-ink-faint">
            صافي الربح محاسبي (مبيعات مسجّلة − التكلفة − المصاريف) ولا يساوي النقد الموجود فعلياً؛ راجع تقرير
            التدفق النقدي.
          </p>
        </Panel>
        <Panel
          title="تطور الربح"
          actions={
            <Pills
              label="تجميع"
              value={options.grain ?? "month"}
              onChange={(grain) => setOptions({ grain })}
              options={[
                ["day", "يومي"],
                ["month", "شهري"],
                ["year", "سنوي"],
              ]}
            />
          }
        >
          <BarChart
            label="تطور الإيرادات وصافي الربح"
            series={["صافي الإيرادات", "صافي الربح"]}
            groups={data.trend.map((t) => ({
              key: t.key,
              label: bucketLabel(t.key),
              values: [t.revenue, t.net_profit],
            }))}
          />
        </Panel>
      </div>
    </>
  );
}

function ExpensesView({ data, options, setOptions }: ViewProps<"expenses">) {
  return (
    <>
      <Metrics
        items={[
          { label: "إجمالي المصاريف", value: data.metrics.total, money: true, tone: "bad" },
          { label: "عدد عمليات الصرف", value: data.metrics.count },
          {
            label: "أكبر تصنيف",
            value: data.breakdown.by === "category" ? (data.breakdown.rows[0]?.amount ?? 0) : null,
            money: true,
          },
          {
            label: "التغير عن الفترة السابقة",
            value: data.metrics.change_pct,
            suffix: "%",
            tone: (data.metrics.change_pct ?? 0) > 0 ? "bad" : "good",
          },
        ]}
      />
      <Panel
        title="المصاريف حسب"
        actions={
          <Pills
            label="تجميع المصاريف"
            value={options.by ?? "category"}
            onChange={(by) => setOptions({ by, page: 1 })}
            options={[
              ["category", "التصنيف"],
              ["employee", "الموظف"],
              ["branch", "الفرع"],
              ["account", "الحساب المالي"],
              ["month", "الفترة"],
            ]}
          />
        }
      >
        <Bars rows={data.breakdown.rows} />
      </Panel>
      <Panel title="عمليات الصرف">
        <Table
          label="عمليات الصرف"
          rowKey={(r) => String(r.id)}
          rows={data.rows}
          pagination={data.pagination}
          onPage={(page, pageSize) => setOptions({ page, pageSize })}
          columns={[
            {
              id: "date",
              header: "التاريخ",
              cell: (r) => <span className="ltr-isolate text-ink-soft">{r.date ?? "—"}</span>,
            },
            { id: "id", header: "رقم العملية", cell: (r) => <span className="ltr-isolate">#{r.id}</span> },
            { id: "category", header: "التصنيف", cell: (r) => r.category },
            {
              id: "description",
              header: "الوصف",
              cell: (r) => <span className="block max-w-[260px] truncate">{r.description || "—"}</span>,
            },
            { id: "amount", header: "المبلغ", cell: (r) => money(r.amount), money: true },
            { id: "employee", header: "الموظف", cell: (r) => r.employee || "—" },
            { id: "branch", header: "الفرع", cell: (r) => r.branch || "—" },
            { id: "method", header: "طريقة الدفع", cell: (r) => r.payment_method },
            { id: "account", header: "الحساب", cell: (r) => r.account || "—" },
          ]}
        />
      </Panel>
    </>
  );
}

function CashView({ data, setOptions }: ViewProps<"cash">) {
  const m = data.metrics;
  return (
    <>
      <Metrics
        items={[
          { label: "الرصيد الافتتاحي", value: m.opening, money: true },
          { label: "إجمالي المقبوضات", value: m.cash_in, money: true, tone: "good" },
          { label: "إجمالي المدفوعات", value: m.cash_out, money: true, tone: "bad" },
          { label: "الرصيد في نهاية الفترة", value: m.closing, money: true },
          { label: "التحويلات بين الحسابات", value: m.transfers, money: true },
        ]}
      />
      <Panel title="الحسابات المالية">
        <Table
          label="الحسابات المالية"
          rowKey={(r) => String(r.id)}
          rows={data.accounts}
          columns={[
            { id: "name", header: "الحساب", cell: (r) => <span className="font-semibold">{r.name}</span> },
            { id: "type", header: "النوع", cell: (r) => (r.is_cash ? "صندوق نقدي" : "بنك / محفظة") },
            { id: "opening", header: "الرصيد الافتتاحي", cell: (r) => money(r.opening) },
            { id: "in", header: "الداخل", cell: (r) => <Money value={r.cash_in} className="text-success" /> },
            {
              id: "out",
              header: "الخارج",
              cell: (r) => <Money value={r.cash_out} className="text-danger" />,
            },
            {
              id: "closing",
              header: "الرصيد",
              cell: (r) => <Money value={r.closing} className="font-bold" />,
            },
            {
              id: "last",
              header: "آخر حركة",
              cell: (r) => <span className="ltr-isolate text-ink-soft">{r.last_movement ?? "—"}</span>,
            },
          ]}
        />
      </Panel>
      <Panel title="الحركات">
        <Table
          label="حركات الحسابات"
          rowKey={(r, i) => `${r.date}-${r.reference}-${i}`}
          rows={data.rows}
          pagination={data.pagination}
          onPage={(page, pageSize) => setOptions({ page, pageSize })}
          columns={[
            {
              id: "date",
              header: "التاريخ",
              cell: (r) => <span className="ltr-isolate text-ink-soft">{r.date}</span>,
            },
            { id: "account", header: "الحساب", cell: (r) => r.account },
            { id: "type", header: "نوع الحركة", cell: (r) => (r.is_transfer ? "تحويل" : r.type) },
            {
              id: "reference",
              header: "المرجع",
              cell: (r) =>
                r.invoice_id ? (
                  <EntityLink kind="invoice" id={r.invoice_id}>
                    <span className="ltr-isolate">#{r.invoice_id}</span>
                  </EntityLink>
                ) : (
                  <span className="ltr-isolate text-ink-soft">{r.reference}</span>
                ),
            },
            {
              id: "reason",
              header: "البيان",
              cell: (r) => (
                <span className="block max-w-[280px] truncate" title={r.description}>
                  {r.reason}
                </span>
              ),
            },
            {
              id: "in",
              header: "داخل",
              cell: (r) => (r.cash_in ? <Money value={r.cash_in} className="text-success" /> : "—"),
            },
            {
              id: "out",
              header: "خارج",
              cell: (r) => (r.cash_out ? <Money value={r.cash_out} className="text-danger" /> : "—"),
            },
            { id: "balance", header: "الرصيد", cell: (r) => <Money value={r.balance ?? null} /> },
          ]}
        />
      </Panel>
      <Panel title="التحويلات بين الحسابات">
        <p className="mb-2 text-xs text-ink-faint">
          التحويل بين حسابين داخليين لا يُحتسب إيراداً ولا مصروفاً.
        </p>
        <Table
          label="التحويلات"
          rowKey={(r) => String(r.id)}
          rows={data.transfers}
          columns={[
            {
              id: "date",
              header: "التاريخ",
              cell: (r) => <span className="ltr-isolate text-ink-soft">{r.date ?? "—"}</span>,
            },
            { id: "from", header: "من", cell: (r) => r.from },
            { id: "to", header: "إلى", cell: (r) => r.to },
            { id: "amount", header: "المبلغ", cell: (r) => money(r.amount) },
            { id: "note", header: "ملاحظة", cell: (r) => r.note || "—" },
          ]}
        />
      </Panel>
    </>
  );
}

function CustomersView({ data, options, setOptions }: ViewProps<"customers">) {
  const m = data.metrics;
  const tab = data.tab;
  return (
    <>
      <Metrics
        items={[
          { label: "إجمالي الدين", value: m.receivables, money: true, tone: "bad" },
          { label: "المستحق اليوم", value: m.due_today, money: true },
          { label: "المتأخر", value: m.overdue, money: true, tone: "warn" },
          { label: "المبيعات الآجلة", value: m.credit_sales, money: true },
          { label: "إجمالي التحصيلات", value: m.collections, money: true, tone: "good" },
        ]}
      />
      <Panel title="أعمار الديون">
        <BarChart
          label="أعمار الديون"
          series={["المبلغ"]}
          groups={data.aging.map((a) => ({ key: a.key, label: a.label, values: [a.amount] }))}
          height={170}
        />
        <p className="mt-2 text-xs text-ink-faint">
          تاريخ الاستحقاق هو تاريخ الفاتورة، لأن FINORA لا يسجّل أجلاً للفواتير الآجلة.
        </p>
      </Panel>
      <Panel
        title={tab === "debts" ? "الديون المفتوحة" : "العملاء"}
        actions={
          <Pills
            label="القسم"
            value={options.tab ?? "customers"}
            onChange={(t) => setOptions({ tab: t, page: 1 })}
            options={[
              ["customers", "العملاء"],
              ["debts", "الديون"],
            ]}
          />
        }
      >
        {tab === "debts" ? (
          <Table
            label="الديون المفتوحة"
            rowKey={(r, i) => ("invoice_id" in r ? String(r.invoice_id) : String(i))}
            rows={data.rows.filter(
              (r): r is Extract<CustomersReport["rows"][number], { invoice_id: number }> => "invoice_id" in r,
            )}
            pagination={data.pagination}
            onPage={(page, pageSize) => setOptions({ page, pageSize })}
            columns={[
              {
                id: "customer",
                header: "العميل",
                cell: (r) => (
                  <EntityLink kind="customer" id={r.customer_id}>
                    {r.customer || "—"}
                  </EntityLink>
                ),
              },
              {
                id: "phone",
                header: "الهاتف",
                cell: (r) => <span className="ltr-isolate">{r.phone || "—"}</span>,
              },
              {
                id: "invoice",
                header: "الفاتورة",
                cell: (r) => (
                  <EntityLink kind="invoice" id={r.invoice_id}>
                    <span className="ltr-isolate">#{r.invoice_id}</span>
                  </EntityLink>
                ),
              },
              { id: "total", header: "إجمالي الدين", cell: (r) => money(r.total) },
              { id: "paid", header: "المدفوع", cell: (r) => money(r.paid) },
              {
                id: "remaining",
                header: "المتبقي",
                cell: (r) => <Money value={r.remaining} className="font-bold text-danger" />,
              },
              {
                id: "due",
                header: "تاريخ الاستحقاق",
                cell: (r) => <span className="ltr-isolate">{r.due_date}</span>,
              },
              {
                id: "days",
                header: "أيام التأخير",
                cell: (r) => (
                  <span className={r.days_overdue > 60 ? "font-bold text-danger" : ""}>
                    {formatNumber(r.days_overdue)}
                  </span>
                ),
              },
            ]}
          />
        ) : (
          <Table
            label="العملاء"
            rowKey={(r, i) => ("name" in r ? `${r.customer_id ?? "x"}-${i}` : String(i))}
            rows={data.rows.filter(
              (r): r is Extract<CustomersReport["rows"][number], { name: string }> => "name" in r,
            )}
            pagination={data.pagination}
            onPage={(page, pageSize) => setOptions({ page, pageSize })}
            columns={[
              {
                id: "name",
                header: "الاسم",
                cell: (r) => (
                  <EntityLink kind="customer" id={r.customer_id}>
                    {r.name}
                  </EntityLink>
                ),
              },
              {
                id: "phone",
                header: "الهاتف",
                cell: (r) => <span className="ltr-isolate">{r.phone || "—"}</span>,
              },
              { id: "orders", header: "عدد الطلبات", cell: (r) => formatNumber(r.orders) },
              { id: "purchases", header: "إجمالي المشتريات", cell: (r) => money(r.purchases) },
              { id: "paid", header: "إجمالي المدفوع", cell: (r) => money(r.paid) },
              {
                id: "debt",
                header: "الدين الحالي",
                cell: (r) => <Money value={r.debt} className={r.debt > 0 ? "font-bold text-danger" : ""} />,
              },
              {
                id: "last",
                header: "آخر عملية شراء",
                cell: (r) => <span className="ltr-isolate text-ink-soft">{r.last_purchase ?? "—"}</span>,
              },
            ]}
          />
        )}
      </Panel>
    </>
  );
}

function PurchasesView({ data, options, setOptions }: ViewProps<"purchases">) {
  const m = data.metrics;
  type PurchaseRow = Extract<PurchasesReport["rows"][number], { purchase_id: number }>;
  type SupplierRow = Extract<PurchasesReport["rows"][number], { balance: number }>;
  return (
    <>
      <Metrics
        items={[
          { label: "إجمالي المشتريات", value: m.amount, money: true },
          { label: "عدد فواتير الشراء", value: m.count },
          { label: "الكميات المستلمة", value: m.quantity },
          { label: "المدفوع", value: m.paid, money: true, tone: "good" },
          { label: "المتبقي من مشتريات الفترة", value: m.remaining, money: true, tone: "warn" },
          { label: "ديون الموردين (كل الفترات)", value: m.supplier_debts, money: true, tone: "bad" },
        ]}
      />
      <Panel title="المشتريات حسب المورد">
        <Bars
          rows={data.by_supplier.map((s) => ({
            key: String(s.supplier_id ?? ""),
            label: s.name,
            count: s.count,
            amount: s.amount,
          }))}
        />
      </Panel>
      <Panel
        title="التفاصيل"
        actions={
          <Pills
            label="القسم"
            value={options.tab ?? "purchases"}
            onChange={(t) => setOptions({ tab: t, page: 1 })}
            options={[
              ["purchases", "المشتريات"],
              ["suppliers", "الموردون"],
              ["debts", "ديون الموردين"],
            ]}
          />
        }
      >
        {data.tab === "suppliers" ? (
          <Table
            label="الموردون"
            rowKey={(r) => String(r.supplier_id)}
            rows={data.rows.filter((r): r is SupplierRow => "balance" in r)}
            pagination={data.pagination}
            onPage={(page, pageSize) => setOptions({ page, pageSize })}
            columns={[
              {
                id: "name",
                header: "المورد",
                cell: (r) => (
                  <EntityLink kind="supplier" id={r.supplier_id}>
                    {r.name}
                  </EntityLink>
                ),
              },
              { id: "purchases", header: "مشتريات الفترة", cell: (r) => money(r.purchases) },
              { id: "invoices", header: "عدد الفواتير", cell: (r) => formatNumber(r.invoices) },
              { id: "paid", header: "إجمالي المدفوع", cell: (r) => money(r.total_paid) },
              {
                id: "balance",
                header: "الرصيد المستحق",
                cell: (r) => (
                  <Money value={r.balance} className={r.balance > 0 ? "font-bold text-danger" : ""} />
                ),
              },
              {
                id: "last",
                header: "آخر عملية شراء",
                cell: (r) => <span className="ltr-isolate text-ink-soft">{r.last_purchase ?? "—"}</span>,
              },
            ]}
          />
        ) : (
          <Table
            label={data.tab === "debts" ? "ديون الموردين" : "فواتير الشراء"}
            rowKey={(r) => String(r.purchase_id)}
            rows={data.rows.filter((r): r is PurchaseRow => "purchase_id" in r)}
            pagination={data.pagination}
            onPage={(page, pageSize) => setOptions({ page, pageSize })}
            columns={[
              {
                id: "date",
                header: "التاريخ",
                cell: (r) => <span className="ltr-isolate text-ink-soft">{r.date ?? "—"}</span>,
              },
              {
                id: "no",
                header: "الفاتورة",
                cell: (r) => <span className="ltr-isolate">{r.invoice_no}</span>,
              },
              {
                id: "supplier",
                header: "المورد",
                cell: (r) => (
                  <EntityLink kind="supplier" id={r.supplier_id}>
                    {r.supplier || "—"}
                  </EntityLink>
                ),
              },
              { id: "amount", header: "المبلغ", cell: (r) => money(r.amount) },
              { id: "paid", header: "المدفوع", cell: (r) => money(r.paid) },
              {
                id: "remaining",
                header: "المتبقي",
                cell: (r) => <Money value={r.remaining} className={r.remaining > 0 ? "text-danger" : ""} />,
              },
              { id: "status", header: "الحالة", cell: (r) => (r.remaining > 0 ? "غير مسددة" : "مسددة") },
            ]}
          />
        )}
      </Panel>
    </>
  );
}

function cellText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "number" ? formatNumber(value) : value;
}

function InventoryView({ data, options, setOptions }: ViewProps<"inventory">) {
  const m = data.metrics;
  const [search, setSearch] = useState(options.search ?? "");
  useEffect(() => {
    const t = setTimeout(() => {
      if ((options.search ?? "") !== search) setOptions({ search, page: 1 });
    }, 350);
    return () => clearTimeout(t);
  }, [search, options.search, setOptions]);
  const row = (r: InventoryReport["rows"][number], key: string) => r[key] ?? null;
  const id = (r: InventoryReport["rows"][number]) => {
    const v = r.product_id;
    return typeof v === "number" ? v : null;
  };
  const columns: Record<string, Array<Column<InventoryReport["rows"][number]>>> = {
    stock: [
      {
        id: "name",
        header: "المنتج",
        cell: (r) => (
          <EntityLink kind="product" id={id(r)}>
            {cellText(row(r, "name"))}
          </EntityLink>
        ),
      },
      {
        id: "sku",
        header: "SKU",
        cell: (r) => <span className="ltr-isolate">{cellText(row(r, "sku"))}</span>,
      },
      { id: "category", header: "التصنيف", cell: (r) => cellText(row(r, "category")) },
      { id: "quantity", header: "الكمية", cell: (r) => cellText(row(r, "quantity")) },
      { id: "available", header: "المتاح", cell: (r) => cellText(row(r, "available")) },
      {
        id: "cost",
        header: "متوسط التكلفة",
        cell: (r) => <Money value={Number(row(r, "average_cost") ?? 0)} />,
      },
      {
        id: "value",
        header: "قيمة المخزون",
        cell: (r) => <Money value={Number(row(r, "value") ?? 0)} className="font-semibold" />,
      },
      { id: "price", header: "سعر البيع", cell: (r) => <Money value={Number(row(r, "sale_price") ?? 0)} /> },
    ],
    low: [
      {
        id: "name",
        header: "المنتج",
        cell: (r) => (
          <EntityLink kind="product" id={id(r)}>
            {cellText(row(r, "name"))}
          </EntityLink>
        ),
      },
      { id: "quantity", header: "الكمية الحالية", cell: (r) => cellText(row(r, "quantity")) },
      { id: "threshold", header: "الحد الأدنى", cell: (r) => cellText(row(r, "threshold")) },
      {
        id: "shortage",
        header: "النقص",
        cell: (r) => <span className="font-bold text-danger">{cellText(row(r, "shortage"))}</span>,
      },
    ],
    stagnant: [
      {
        id: "name",
        header: "المنتج",
        cell: (r) => (
          <EntityLink kind="product" id={typeof r.id === "number" ? r.id : null}>
            {cellText(row(r, "name"))}
          </EntityLink>
        ),
      },
      { id: "quantity", header: "الكمية", cell: (r) => cellText(row(r, "quantity")) },
      {
        id: "value",
        header: "رأس المال المجمد",
        cell: (r) => <Money value={Number(row(r, "value") ?? 0)} className="font-semibold text-warning" />,
      },
      { id: "days", header: "أيام بلا بيع", cell: (r) => cellText(row(r, "days")) },
      {
        id: "last",
        header: "آخر بيع",
        cell: (r) => <span className="ltr-isolate">{cellText(row(r, "last_sale"))}</span>,
      },
    ],
    movements: [
      {
        id: "date",
        header: "التاريخ",
        cell: (r) => <span className="ltr-isolate text-ink-soft">{cellText(row(r, "date"))}</span>,
      },
      {
        id: "product",
        header: "المنتج",
        cell: (r) => (
          <EntityLink kind="product" id={id(r)}>
            {cellText(row(r, "product"))}
          </EntityLink>
        ),
      },
      { id: "type", header: "نوع الحركة", cell: (r) => cellText(row(r, "type")) },
      {
        id: "direction",
        header: "الاتجاه",
        cell: (r) =>
          row(r, "direction") === "in"
            ? "إدخال"
            : row(r, "direction") === "out"
              ? "إخراج"
              : cellText(row(r, "direction")),
      },
      { id: "quantity", header: "الكمية", cell: (r) => cellText(row(r, "quantity")) },
      { id: "value", header: "القيمة", cell: (r) => <Money value={Number(row(r, "value") ?? 0)} /> },
      {
        id: "source",
        header: "المصدر",
        cell: (r) => <span className="ltr-isolate text-ink-soft">{cellText(row(r, "source"))}</span>,
      },
    ],
  };
  return (
    <>
      <Metrics
        items={[
          { label: "الكمية الحالية", value: m.quantity },
          { label: "قيمة المخزون", value: m.value, money: true },
          { label: "المنتجات الناقصة", value: m.low_stock, tone: "bad" },
          { label: "المنتجات الراكدة", value: m.stagnant, tone: "warn" },
          { label: "رأس المال المجمد", value: m.stagnant_value, money: true, tone: "warn" },
        ]}
      />
      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title="الركود حسب المدة">
          <BarChart
            label="المنتجات الراكدة"
            series={["رأس المال المجمد"]}
            height={170}
            groups={["30", "60", "90", "180"].map((d) => ({
              key: d,
              label: `${d}+ يوم`,
              values: [m.stagnant_buckets[d]?.value ?? 0],
            }))}
          />
        </Panel>
        <Panel title="الأكثر مبيعاً في الفترة">
          <Bars
            rows={data.best_sellers.map((b) => ({
              key: String(b.product_id ?? b.name),
              label: b.name,
              count: b.quantity,
              amount: b.revenue,
            }))}
          />
        </Panel>
      </div>
      <Panel
        title="التفاصيل"
        actions={
          <>
            {(data.tab === "stock" || data.tab === "low") && (
              <input
                type="search"
                aria-label="بحث في المنتجات"
                placeholder="بحث بالاسم أو SKU أو الباركود"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-9 w-56 rounded-control border border-line bg-white px-3 text-sm outline-none focus:border-violet/45"
              />
            )}
            <Pills
              label="القسم"
              value={options.tab ?? "stock"}
              onChange={(t) => setOptions({ tab: t, page: 1 })}
              options={[
                ["stock", "حالة المخزون"],
                ["low", "الناقصة"],
                ["stagnant", "الراكدة"],
                ["movements", "حركة المخزون"],
              ]}
            />
          </>
        }
      >
        <Table
          label="المخزون"
          rowKey={(r, i) => `${String(r.product_id ?? r.id ?? "")}-${i}`}
          rows={data.rows}
          columns={columns[data.tab] ?? []}
          pagination={data.pagination}
          onPage={(page, pageSize) => setOptions({ page, pageSize })}
        />
        <p className="mt-2 text-xs text-ink-faint">
          القيمة حسب تقييم FINORA الفعلي (طبقات التكلفة FIFO، وسعر الشراء عند عدم توفرها).
        </p>
      </Panel>
    </>
  );
}

function InvoicesView({ data, options, setOptions }: ViewProps<"invoices">) {
  const m = data.metrics;
  return (
    <>
      <Metrics
        items={[
          { label: "إجمالي الفواتير", value: m.total },
          { label: "قيمة الفواتير السارية", value: m.amount, money: true },
          { label: "المتبقي للتحصيل", value: m.outstanding, money: true, tone: "warn" },
          { label: "الملغاة", value: m.cancelled, tone: "bad" },
          { label: "المرتجعة", value: m.returned },
        ]}
      />
      <Panel
        title="الفواتير"
        actions={
          <Pills
            label="الحالة"
            value={options.state ?? "all"}
            onChange={(state) => setOptions({ state, page: 1 })}
            options={[
              ["all", `الكل (${formatNumber(m.total)})`],
              ["paid", `المدفوعة (${formatNumber(m.paid)})`],
              ["partial", `الجزئية (${formatNumber(m.partial)})`],
              ["credit", `الآجلة (${formatNumber(m.credit)})`],
              ["cancelled", `الملغاة (${formatNumber(m.cancelled)})`],
              ["returned", `المرتجعة (${formatNumber(m.returned)})`],
            ]}
          />
        }
      >
        <Table
          label="الفواتير"
          columns={invoiceColumns(true)}
          rows={data.rows}
          rowKey={(r) => String(r.id)}
          pagination={data.pagination}
          onPage={(page, pageSize) => setOptions({ page, pageSize })}
        />
      </Panel>
    </>
  );
}

function EmployeesView({ data, options, setOptions }: ViewProps<"employees">) {
  const columns: Array<Column<EmployeesReport["rows"][number]>> = [
    {
      id: "name",
      header: "الموظف",
      cell: (r) => (
        <EntityLink kind="employee" id={r.employee_id}>
          {r.name}
        </EntityLink>
      ),
    },
    { id: "sales", header: "المبيعات", cell: (r) => <Money value={r.sales} className="font-semibold" /> },
    { id: "orders", header: "عدد الطلبات", cell: (r) => formatNumber(r.orders) },
    { id: "average", header: "متوسط الطلب", cell: (r) => money(r.average) },
    { id: "collections", header: "التحصيلات", cell: (r) => money(r.collections) },
    { id: "discounts", header: "الخصومات", cell: (r) => money(r.discounts) },
    { id: "returns", header: "المرتجعات", cell: (r) => money(r.returns) },
    ...(data.show_profit
      ? [
          {
            id: "profit",
            header: "الربح",
            cell: (r: EmployeesReport["rows"][number]) => <Money value={r.profit} className="text-success" />,
          },
        ]
      : []),
    { id: "commission", header: "العمولة", cell: (r) => money(r.commission) },
  ];
  const t = data.totals;
  return (
    <>
      <Metrics
        items={[
          { label: "إجمالي المبيعات", value: t.sales, money: true },
          { label: "عدد الطلبات", value: t.orders },
          { label: "التحصيلات", value: t.collections, money: true, tone: "good" },
          { label: "الخصومات", value: t.discounts, money: true, tone: "warn" },
          { label: "العمولات", value: t.commission, money: true },
        ]}
      />
      <Panel
        title="أداء الموظفين"
        actions={
          <Pills
            label="الترتيب"
            value={options.sort ?? "sales"}
            onChange={(sort) => setOptions({ sort })}
            options={[
              ["sales", "المبيعات"],
              ["collections", "التحصيل"],
              ...(data.show_profit ? ([["profit", "الربح"]] as Array<[string, string]>) : []),
              ["orders", "عدد الطلبات"],
            ]}
          />
        }
      >
        <Table
          label="أداء الموظفين"
          columns={columns}
          rows={data.rows}
          rowKey={(r, i) => `${r.employee_id ?? "none"}-${i}`}
        />
      </Panel>
    </>
  );
}

function CashflowView({ data, options, setOptions }: ViewProps<"cashflow">) {
  const f = data.flow;
  return (
    <>
      <Metrics
        items={[
          { label: "الرصيد الافتتاحي", value: f.opening, money: true },
          { label: "التدفقات الداخلة", value: f.inflow, money: true, tone: "good" },
          { label: "التدفقات الخارجة", value: f.outflow, money: true, tone: "bad" },
          { label: "صافي التدفق النقدي", value: f.net, money: true, tone: f.net >= 0 ? "good" : "bad" },
          { label: "الرصيد النقدي الختامي", value: f.closing, money: true },
        ]}
      />
      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title="التدفقات الداخلة">
          <Bars rows={f.inflows.map((r) => ({ key: r.key, label: r.label, count: 0, amount: r.amount }))} />
        </Panel>
        <Panel title="التدفقات الخارجة">
          <Bars rows={f.outflows.map((r) => ({ key: r.key, label: r.label, count: 0, amount: r.amount }))} />
        </Panel>
      </div>
      <Panel title="النتيجة">
        <div className="grid gap-1 text-[14px] sm:max-w-[460px]">
          {[
            ["الرصيد الافتتاحي", f.opening, ""],
            ["+ إجمالي التدفقات الداخلة", f.inflow, "text-success"],
            ["− إجمالي التدفقات الخارجة", f.outflow, "text-danger"],
            ...(f.net_transfers !== 0
              ? ([["± صافي التحويلات مع حسابات خارج الفلتر", f.net_transfers, ""]] as Array<
                  [string, number, string]
                >)
              : []),
          ].map(([label, value, tone]) => (
            <div
              key={String(label)}
              className="flex items-center justify-between border-b border-line/50 py-1.5"
            >
              <span className="text-ink-soft">{label}</span>
              <Money value={Number(value)} className={String(tone)} />
            </div>
          ))}
          <div className="mt-1 flex items-center justify-between rounded-control bg-success-soft/60 px-3 py-2 font-bold">
            <span>= الرصيد النقدي الختامي</span>
            <Money value={f.closing} />
          </div>
        </div>
        <p className="mt-2 text-xs text-ink-faint">
          المبيعات الآجلة غير المحصّلة لا تدخل التدفق النقدي. الرواتب المدفوعة تظهر ضمن المصاريف المدفوعة.
        </p>
      </Panel>
      <Panel
        title="التدفق عبر الزمن"
        actions={
          <Pills
            label="تجميع"
            value={options.grain ?? "day"}
            onChange={(grain) => setOptions({ grain })}
            options={[
              ["day", "يومي"],
              ["week", "أسبوعي"],
              ["month", "شهري"],
            ]}
          />
        }
      >
        <BarChart
          label="الداخل والخارج"
          series={["الداخل", "الخارج"]}
          groups={data.series.map((p) => ({
            key: p.key,
            label: bucketLabel(p.key),
            values: [p.inflow, p.outflow],
          }))}
        />
      </Panel>
    </>
  );
}

const VIEWS: { [K in ReportSection]: (props: ViewProps<K>) => ReactNode } = {
  sales: SalesView,
  profit: ProfitView,
  expenses: ExpensesView,
  cash: CashView,
  customers: CustomersView,
  purchases: PurchasesView,
  inventory: InventoryView,
  invoices: InvoicesView,
  employees: EmployeesView,
  cashflow: CashflowView,
  equity: EquityView,
};

function EquityView({ data }: ViewProps<"equity">) {
  const pos = data.position;
  const LineRow = ({ label, amount, strong }: { label: string; amount: number; strong?: boolean }) => (
    <tr className={cn("border-t border-line/50", strong && "bg-violet-soft/40 font-bold")}>
      <td className="px-2 py-2">{label}</td>
      <td className="px-2 py-2">
        <Money value={amount} />
      </td>
    </tr>
  );
  return (
    <>
      <Metrics
        items={[
          {
            label: "حقوق الملكية (ما تملكه فعلاً)",
            value: pos.equity,
            money: true,
            tone: pos.equity >= 0 ? "good" : "bad",
          },
          { label: "إجمالي الأصول", value: pos.total_assets, money: true },
          { label: "إجمالي الالتزامات", value: pos.total_liabilities, money: true },
          {
            label: "صافي ربح الفترة",
            value: data.profit.net_profit,
            money: true,
            tone: data.profit.net_profit >= 0 ? "good" : "bad",
          },
          { label: "التغيّر في النقد", value: data.cash.net_change, money: true },
        ]}
      />
      <Panel title="باختصار">
        <ul aria-label="ملخص أين ذهبت الأرباح" className="space-y-1.5 text-[14px] leading-7">
          {data.summary.map((line) => (
            <li key={line}>• {line}</li>
          ))}
        </ul>
      </Panel>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="ما تملكه الشركة وما عليها (الآن)">
          <table aria-label="المركز المالي" className="w-full text-[13.5px]">
            <tbody>
              <tr>
                <td colSpan={2} className="px-2 pb-1 pt-2 text-xs font-bold text-success">
                  الأصول — ما تملكه
                </td>
              </tr>
              {pos.assets.map((a) => (
                <LineRow key={`a-${a.key}`} label={a.label} amount={a.amount} />
              ))}
              <LineRow label="إجمالي الأصول" amount={pos.total_assets} strong />
              <tr>
                <td colSpan={2} className="px-2 pb-1 pt-4 text-xs font-bold text-danger">
                  الالتزامات — ما عليك
                </td>
              </tr>
              {pos.liabilities.map((l) => (
                <LineRow key={`l-${l.key}`} label={l.label} amount={l.amount} />
              ))}
              <LineRow label="إجمالي الالتزامات" amount={pos.total_liabilities} strong />
              <LineRow label="= حقوق الملكية (الأصول − الالتزامات)" amount={pos.equity} strong />
            </tbody>
          </table>
          <p className="mt-3 text-xs leading-5 text-ink-faint">{pos.note}</p>
        </Panel>
        <Panel title="أين ذهب ربح هذه الفترة">
          <table aria-label="أين ذهب الربح" className="w-full text-[13.5px]">
            <tbody>
              <LineRow label="صافي ربح الفترة" amount={data.profit.net_profit} strong />
              {data.bridge
                .filter((b) => b.amount !== 0)
                .map((b) => (
                  <tr key={b.key} className="border-t border-line/50">
                    <td className="px-2 py-2">
                      <span className={b.amount < 0 ? "text-danger" : "text-success"} aria-hidden>
                        {b.amount < 0 ? "− " : "+ "}
                      </span>
                      {b.label}
                    </td>
                    <td className="px-2 py-2">
                      <Money value={b.amount} />
                    </td>
                  </tr>
                ))}
              <LineRow
                label="= التغيّر الفعلي في النقد (الصناديق والبنوك)"
                amount={data.cash.net_change}
                strong
              />
            </tbody>
          </table>
          <p className="mt-3 text-xs leading-5 text-ink-faint">
            «−» يعني أن هذا الجزء من الربح لم يبقَ نقداً (صار مخزوناً أو ديناً عند الزبائن أو سُحب)، و«+» يعني
            نقداً دخل من غير ربح الفترة. البنود تُغلق تماماً على حركة الخزينة الفعلية: من
            <Money value={data.cash.opening} /> إلى <Money value={data.cash.closing} />.
          </p>
        </Panel>
      </div>
    </>
  );
}

function renderView<K extends ReportSection>(section: K, props: ViewProps<K>): ReactNode {
  const View = VIEWS[section] as (p: ViewProps<K>) => ReactNode;
  return <View {...props} />;
}

export function SectionReport({
  section,
  filters,
  active,
  onBack,
  onOptions,
}: {
  section: ReportSection;
  filters: ReportFilters;
  active: boolean;
  onBack(): void;
  onOptions(options: SectionOptions): void;
}) {
  const [options, setOptionsState] = useState<SectionOptions>({});
  const setOptions = useMemo(
    () => (patch: SectionOptions) =>
      setOptionsState((current) => {
        const next = { ...current, ...patch };
        onOptions(next);
        return next;
      }),
    [onOptions],
  );
  const query = useQuery({
    queryKey: ["reports", "section", section, filters, options],
    queryFn: () => finora.reports.section(section, filters, { pageSize: 50, ...options }),
    enabled: active,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
  const info = SECTION_INFO[section];
  const Icon = info.icon;
  const data = query.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          className="flex h-9 items-center gap-1.5 rounded-control bg-white px-3 text-sm font-semibold text-ink-soft shadow-control ring-1 ring-line/60 hover:text-violet-deep"
        >
          <ArrowRight size={16} aria-hidden />
          لوحة التقارير
        </button>
        <span className="grid h-9 w-9 place-items-center rounded-control bg-violet-soft text-violet-deep">
          <Icon size={18} aria-hidden />
        </span>
        <h2 className="text-[19px] font-bold text-ink">{info.title}</h2>
        {data && (
          <span className="ltr-isolate rounded-full bg-surface-sunken px-3 py-1 text-xs text-ink-soft">
            {data.filters.date_from} — {data.filters.date_to}
          </span>
        )}
        {query.isFetching && <span className="text-xs text-ink-faint">جارٍ التحديث…</span>}
      </div>
      {query.error && !data ? (
        <p role="alert" className="rounded-control bg-danger-soft px-4 py-3 text-sm text-danger">
          {toFinoraError(query.error).message}
        </p>
      ) : !data ? (
        <div className="space-y-3" aria-busy aria-label={`جارٍ تحميل ${info.title}`}>
          <span className="block h-24 animate-pulse rounded-panel bg-white/80" />
          <span className="block h-72 animate-pulse rounded-panel bg-white/80" />
        </div>
      ) : (
        <div
          className={cn(
            "min-h-0 flex-1 space-y-3 overflow-y-auto pb-2 transition-opacity",
            query.isFetching && "opacity-80",
          )}
        >
          {renderView(section, { data, options, setOptions } as ViewProps<typeof section>)}
        </div>
      )}
    </div>
  );
}

export type {
  CashflowReport,
  CashReport,
  CustomersReport,
  ExpensesReport,
  InvoicesReport,
  ProfitReport,
  PurchasesReport,
  SalesReport,
};
