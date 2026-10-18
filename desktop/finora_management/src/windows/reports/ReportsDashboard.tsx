import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowDownLeft,
  ArrowLeftRight,
  ArrowUp,
  ArrowUpRight,
  Ban,
  CheckCircle2,
  Clock,
  Coins,
  Equal,
  ExternalLink,
  Hourglass,
  Minus,
  PackageCheck,
  RotateCcw,
  Star,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { Dashboard, Kpi, ReportFilters, ReportSection } from "@/api/finora/reports";
import { bucketLabel, KPI_ICONS, SECTION_INFO } from "@/features/reports/labels";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { BarChart, LineChart, SERIES_COLORS } from "./charts";

type Grain = "day" | "month" | "year";

export function Money({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined)
    return <span className={cn("text-ink-faint", className)}>—</span>;
  return (
    <span className={cn("ltr-isolate whitespace-nowrap", className)}>
      {formatNumber(value)} <span className="text-[0.78em] font-normal text-ink-faint">د.ع</span>
    </span>
  );
}

export function Change({ pct, tone }: { pct: number | null; tone: Kpi["tone"] }) {
  if (pct === null) return <span className="text-xs text-ink-faint">لا تتوفر مقارنة</span>;
  const Icon = pct > 0 ? ArrowUp : pct < 0 ? ArrowDown : Minus;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-[12.5px] font-semibold",
        tone === "good" ? "text-success" : tone === "bad" ? "text-danger" : "text-ink-soft",
      )}
    >
      <Icon size={13} strokeWidth={2.6} aria-hidden />
      <span className="ltr-isolate">
        {pct > 0 ? "+" : ""}
        {pct.toFixed(1)}%
      </span>
    </span>
  );
}

const KPI_TONES: Record<string, string> = {
  sales: "bg-violet-soft text-violet-deep",
  net_profit: "bg-azure-soft text-azure",
  expenses: "bg-warning-soft text-warning",
  cash: "bg-success-soft text-success",
  receivables: "bg-danger-soft text-danger",
  inventory: "bg-violet-soft text-violet",
};

function KpiCard({ kpi, onOpen }: { kpi: Kpi; onOpen(): void }) {
  const Icon = KPI_ICONS[kpi.key] ?? Coins;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${kpi.label} — فتح التقرير`}
      className="flex min-w-0 flex-col gap-2 rounded-panel bg-white px-4 py-3.5 text-start shadow-control ring-1 ring-line/60 transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-glass"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13.5px] font-semibold text-ink">{kpi.label}</p>
          <Money value={kpi.value} className="mt-1 block text-[21px] font-bold text-ink" />
        </div>
        <span
          className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-control", KPI_TONES[kpi.key])}
        >
          <Icon size={19} aria-hidden />
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-ink-faint">مقارنة بالفترة السابقة</span>
        <Change pct={kpi.change_pct} tone={kpi.tone} />
      </div>
    </button>
  );
}

function Card({
  title,
  icon: Icon,
  onOpen,
  children,
  actions,
  className,
}: {
  title: string;
  icon: LucideIcon;
  onOpen?(): void;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={title}
      className={cn(
        "flex min-w-0 flex-col rounded-panel bg-white p-4 shadow-control ring-1 ring-line/60",
        className,
      )}
    >
      <header className="mb-2.5 flex items-center gap-2">
        <Icon size={17} className="text-violet" aria-hidden />
        <h3 className="text-[15px] font-bold text-ink">{title}</h3>
        {actions}
        {onOpen && (
          <button
            type="button"
            onClick={onOpen}
            aria-label={`فتح تفاصيل ${title}`}
            className="ms-auto flex items-center gap-1 rounded-[9px] px-2 py-1 text-xs font-semibold text-azure transition-colors hover:bg-azure-soft"
          >
            فتح التفاصيل
            <ExternalLink size={13} aria-hidden />
          </button>
        )}
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}

function Line({
  icon: Icon,
  tone = "text-ink-soft",
  label,
  children,
  strong,
}: {
  icon?: LucideIcon;
  tone?: string;
  label: string;
  children: ReactNode;
  strong?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 py-1.5 text-[13px]",
        strong && "mt-1 rounded-control bg-success-soft/60 px-2.5 py-2",
      )}
    >
      {Icon && <Icon size={15} className={cn("shrink-0", tone)} aria-hidden />}
      <span className={cn("min-w-0 flex-1 truncate", strong ? "font-bold text-ink" : "text-ink-soft")}>
        {label}
      </span>
      <span className={cn(strong ? "text-[15px] font-bold text-ink" : "font-semibold text-ink")}>
        {children}
      </span>
    </div>
  );
}

function RankList({ title, rows }: { title: string; rows: Array<{ name: string; amount: number }> }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-1.5">
      <p className="mb-1 rounded-[8px] bg-surface-sunken px-2 py-1 text-[11.5px] font-semibold text-ink-soft">
        {title}
      </p>
      <ol className="space-y-1">
        {rows.map((row, i) => (
          <li key={`${row.name}-${i}`} className="flex items-center gap-2 text-[12.5px]">
            <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-violet-soft text-[10.5px] font-bold text-violet-deep">
              {i + 1}
            </span>
            <span className="min-w-0 flex-1 truncate text-ink">{row.name}</span>
            <Money value={row.amount} className="text-ink-soft" />
          </li>
        ))}
      </ol>
    </div>
  );
}

function Segmented<T extends string>({
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
      className="flex gap-0.5 rounded-control bg-surface-sunken p-0.5"
    >
      {options.map(([id, text]) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={value === id}
          onClick={() => onChange(id)}
          className={cn(
            "h-7 rounded-[9px] px-3 text-xs font-semibold transition-colors",
            value === id ? "bg-violet text-white shadow-control" : "text-ink-soft hover:bg-white",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="grid gap-3" aria-busy aria-label="جارٍ تحميل التقارير">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className="h-[104px] animate-pulse rounded-panel bg-white/80" />
        ))}
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <span className="h-[280px] animate-pulse rounded-panel bg-white/80" />
        <span className="h-[280px] animate-pulse rounded-panel bg-white/80" />
      </div>
    </div>
  );
}

export function ReportsDashboard({
  filters,
  active,
  onOpen,
}: {
  filters: ReportFilters;
  active: boolean;
  onOpen(section: ReportSection): void;
}) {
  const [grain, setGrain] = useState<Grain>("day");
  const query = useQuery({
    queryKey: ["reports", "dashboard", filters, grain],
    queryFn: () => finora.reports.dashboard(filters, grain),
    enabled: active,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
  const data = query.data;
  const linePoints = useMemo(
    () => (data?.sales_series ?? []).map((p) => ({ key: p.key, label: bucketLabel(p.key), value: p.amount })),
    [data?.sales_series],
  );

  if (query.error && !data) {
    return (
      <p role="alert" className="rounded-control bg-danger-soft px-4 py-3 text-sm text-danger">
        {toFinoraError(query.error).message}
      </p>
    );
  }
  if (!data) return <Skeleton />;
  const s = data.sections;
  const can = (section: ReportSection) => data.allowed[section] ?? false;

  return (
    <div
      className={cn(
        "min-h-0 flex-1 space-y-3 overflow-y-auto pb-2 transition-opacity",
        query.isFetching && "opacity-80",
      )}
    >
      {data.employee_scoped && (
        <p className="rounded-control bg-azure-soft px-3.5 py-2 text-xs text-azure">
          فلتر الموظف يطبّق على المبيعات والفواتير والمصاريف والمشتريات المسجلة باسمه. النقد والمخزون والديون
          العامة لا تُنسب لموظف.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
        {data.kpis.map((kpi) => (
          <KpiCard key={kpi.key} kpi={kpi} onOpen={() => onOpen(kpi.section)} />
        ))}
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <Card
          title="حركة المبيعات"
          icon={SECTION_INFO.sales.icon}
          onOpen={() => onOpen("sales")}
          actions={
            <div className="ms-3">
              <Segmented<Grain>
                label="تجميع المبيعات"
                value={grain}
                onChange={setGrain}
                options={[
                  ["day", "يومي"],
                  ["month", "شهري"],
                  ["year", "سنوي"],
                ]}
              />
            </div>
          }
        >
          <LineChart points={linePoints} label="حركة المبيعات" />
        </Card>
        <Card title="مقارنة الفترات" icon={SECTION_INFO.sales.icon}>
          <div className="mb-1 flex flex-wrap gap-3 text-[11.5px] text-ink-soft">
            {["هذه الفترة", "الفترة السابقة", "نفس الفترة من العام الماضي"].map((name, i) => (
              <span key={name} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: SERIES_COLORS[i] }} />
                {name}
              </span>
            ))}
          </div>
          <BarChart
            label="مقارنة الفترات"
            series={["هذه الفترة", "الفترة السابقة", "نفس الفترة من العام الماضي"]}
            groups={data.comparison.map((c) => ({
              key: c.key,
              label: c.label,
              values: [c.current, c.previous, c.last_year],
            }))}
          />
        </Card>
      </div>

      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
        {s.sales && (
          <Card title="المبيعات" icon={SECTION_INFO.sales.icon} onOpen={() => onOpen("sales")}>
            <Line label="إجمالي المبيعات">
              <Money value={s.sales.gross} />
            </Line>
            <Line label="صافي المبيعات">
              <Money value={s.sales.net} />
            </Line>
            <Line label="عدد الفواتير">{formatNumber(s.sales.invoices)}</Line>
            <Line label="متوسط الفاتورة">
              <Money value={s.sales.average} />
            </Line>
            <Line label="التغير عن الفترة السابقة">
              <Change
                pct={s.sales.change_pct}
                tone={s.sales.change_pct === null ? "neutral" : s.sales.change_pct >= 0 ? "good" : "bad"}
              />
            </Line>
          </Card>
        )}
        {s.profit && (
          <Card title="الأرباح والخسائر" icon={SECTION_INFO.profit.icon} onOpen={() => onOpen("profit")}>
            <Line icon={ArrowUp} tone="text-success" label="الإيرادات">
              <Money value={s.profit.revenue} />
            </Line>
            <Line icon={ArrowDown} tone="text-danger" label="تكلفة البضاعة">
              <Money value={s.profit.cogs} />
            </Line>
            <Line icon={ArrowDown} tone="text-danger" label="المصاريف">
              <Money value={s.profit.expenses} />
            </Line>
            <Line icon={Equal} tone="text-ink" label="صافي الربح" strong>
              <Money value={s.profit.net_profit} />
            </Line>
          </Card>
        )}
        {s.expenses && (
          <Card title="المصاريف" icon={SECTION_INFO.expenses.icon} onOpen={() => onOpen("expenses")}>
            <Line label="إجمالي المصاريف">
              <Money value={s.expenses.total} />
            </Line>
            <Line label="عدد عمليات الصرف">{formatNumber(s.expenses.count)}</Line>
            <Line label="أكبر تصنيف">
              {s.expenses.top_category
                ? `${s.expenses.top_category.label} · ${formatNumber(s.expenses.top_category.amount)}`
                : "—"}
            </Line>
            <Line label="التغير">
              <Change
                pct={s.expenses.change_pct}
                tone={s.expenses.change_pct === null ? "neutral" : s.expenses.change_pct > 0 ? "bad" : "good"}
              />
            </Line>
          </Card>
        )}
        {s.cash && (
          <Card title="النقد والبنوك" icon={SECTION_INFO.cash.icon} onOpen={() => onOpen("cash")}>
            <Line icon={ArrowDownLeft} tone="text-success" label="إجمالي المقبوضات">
              <Money value={s.cash.cash_in} />
            </Line>
            <Line icon={ArrowUpRight} tone="text-danger" label="إجمالي المدفوعات">
              <Money value={s.cash.cash_out} />
            </Line>
            <Line icon={Coins} tone="text-azure" label="الأرصدة في نهاية الفترة">
              <Money value={s.cash.balance} />
            </Line>
            <Line icon={ArrowLeftRight} tone="text-violet" label="التحويلات بين الحسابات">
              <Money value={s.cash.transfers} />
            </Line>
          </Card>
        )}
        {s.customers && (
          <Card title="العملاء والديون" icon={SECTION_INFO.customers.icon} onOpen={() => onOpen("customers")}>
            <Line label="المبيعات الآجلة">
              <Money value={s.customers.credit_sales} />
            </Line>
            <Line label="إجمالي التحصيلات">
              <Money value={s.customers.collections} />
            </Line>
            <Line label="ديون العملاء">
              <Money value={s.customers.receivables} className="text-danger" />
            </Line>
            <RankList title="أكبر العملاء مديونية" rows={s.customers.top_debtors} />
          </Card>
        )}
        {s.purchases && (
          <Card
            title="المشتريات والموردين"
            icon={SECTION_INFO.purchases.icon}
            onOpen={() => onOpen("purchases")}
          >
            <Line label="إجمالي المشتريات">
              <Money value={s.purchases.total} />
            </Line>
            <Line label="دفعات الموردين">
              <Money value={s.purchases.supplier_payments} />
            </Line>
            <Line label="ديون الموردين">
              <Money value={s.purchases.supplier_debts} className="text-danger" />
            </Line>
            <RankList title="أكثر الموردين تعاملاً" rows={s.purchases.top_suppliers} />
          </Card>
        )}
        {s.inventory && (
          <Card title="المخزون" icon={SECTION_INFO.inventory.icon} onOpen={() => onOpen("inventory")}>
            <Line icon={PackageCheck} tone="text-success" label="الكمية الحالية">
              {formatNumber(s.inventory.quantity)}
            </Line>
            <Line icon={Coins} tone="text-azure" label="قيمة المخزون">
              <Money value={s.inventory.value} />
            </Line>
            <Line icon={AlertTriangle} tone="text-danger" label="المنتجات الناقصة">
              {formatNumber(s.inventory.low_stock)}
            </Line>
            <Line icon={Hourglass} tone="text-warning" label="المنتجات الراكدة (30+ يوم)">
              {formatNumber(s.inventory.stagnant)}
            </Line>
            <Line icon={Star} tone="text-warning" label="الأكثر مبيعاً">
              <span className="block max-w-[150px] truncate">{s.inventory.best_seller?.name ?? "—"}</span>
            </Line>
          </Card>
        )}
        {s.invoices && (
          <Card title="الفواتير" icon={SECTION_INFO.invoices.icon} onOpen={() => onOpen("invoices")}>
            <Line icon={CheckCircle2} tone="text-success" label="المدفوعة">
              {formatNumber(s.invoices.paid)}
            </Line>
            <Line icon={Clock} tone="text-azure" label="الجزئية">
              {formatNumber(s.invoices.partial)}
            </Line>
            <Line icon={Hourglass} tone="text-warning" label="الآجلة">
              {formatNumber(s.invoices.credit)}
            </Line>
            <Line icon={Ban} tone="text-danger" label="الملغاة">
              {formatNumber(s.invoices.cancelled)}
            </Line>
            <Line icon={RotateCcw} tone="text-ink-soft" label="المرتجعة">
              {formatNumber(s.invoices.returned)}
            </Line>
          </Card>
        )}
        {s.employees && (
          <Card title="الموظفون" icon={SECTION_INFO.employees.icon} onOpen={() => onOpen("employees")}>
            <table className="w-full text-[12.5px]">
              <thead>
                <tr className="bg-surface-sunken text-ink-soft">
                  <th className="rounded-s-[8px] px-2 py-1 text-start font-semibold">الموظف</th>
                  <th className="px-2 py-1 text-start font-semibold">المبيعات</th>
                  <th className="rounded-e-[8px] px-2 py-1 text-start font-semibold">التحصيلات</th>
                </tr>
              </thead>
              <tbody>
                {s.employees.top.map((e, i) => (
                  <tr key={`${e.employee_id ?? "none"}-${i}`}>
                    <td className="max-w-[110px] truncate px-2 py-1.5 text-ink">{e.name}</td>
                    <td className="px-2 py-1.5">
                      <Money value={e.sales} />
                    </td>
                    <td className="px-2 py-1.5">
                      <Money value={e.collections} />
                    </td>
                  </tr>
                ))}
                {s.employees.top.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-2 py-4 text-center text-ink-faint">
                      لا توجد مبيعات في هذه الفترة
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </Card>
        )}
        {s.cashflow && (
          <Card title="التدفق النقدي" icon={SECTION_INFO.cashflow.icon} onOpen={() => onOpen("cashflow")}>
            <Line icon={ArrowDownLeft} tone="text-success" label="إجمالي الدخل الفعلي">
              <Money value={s.cashflow.inflow} />
            </Line>
            <Line icon={ArrowUpRight} tone="text-danger" label="إجمالي الخرج الفعلي">
              <Money value={s.cashflow.outflow} />
            </Line>
            <Line icon={Equal} label="صافي التدفق النقدي" strong>
              <Money value={s.cashflow.net} />
            </Line>
          </Card>
        )}
      </div>
      {!can("profit") && (
        <p className="text-center text-xs text-ink-faint">
          الأرباح والتدفق النقدي تظهر لمن يملك صلاحية «رؤية التقرير المالي الشامل».
        </p>
      )}
    </div>
  );
}

export type { Dashboard };
