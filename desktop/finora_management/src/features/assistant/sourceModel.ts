import { rowsFromData } from "./engine";

/**
 * Turns a FINORA tool result into something a person can read at a glance:
 * KPI cards (with change vs. a previous period when the tool returns one),
 * ranked bars and a compact table. Pure data shaping; values are never recomputed.
 */
export interface Kpi {
  key: string;
  label: string;
  value: number;
  money: boolean;
  previous?: number;
  change?: number | null;
}
export interface BarGroup {
  title: string;
  items: { label: string; value: number; money: boolean }[];
}
export interface SourceTable {
  columns: { key: string; label: string; money: boolean }[];
  rows: Record<string, unknown>[];
}
export interface SourceModel {
  kpis: Kpi[];
  bars: BarGroup[];
  table: SourceTable | null;
}
const LABELS: Record<string, string> = {
  invoices: "عدد الفواتير",
  net_sales: "صافي المبيعات",
  collected: "المحصّل",
  credit_sales: "مبيعات آجلة",
  average_invoice: "متوسط الفاتورة",
  returns: "المرتجعات",
  cogs: "كلفة المبيعات",
  gross_profit: "مجمل الربح",
  operating_expenses: "المصاريف",
  other_expenses: "مصاريف أخرى",
  net_profit: "صافي الربح",
  count: "العدد",
  amount: "المبلغ",
  paid: "المدفوع",
  remaining: "المتبقي",
  quantity: "الكمية",
  supplier_debts: "ديون الموردين",
  receivables: "ذمم العملاء",
  open_invoices: "فواتير مفتوحة",
  due_today: "مستحق اليوم",
  overdue: "متأخر",
  returns_count: "عدد المرتجعات",
  returns_amount: "مبلغ المرتجعات",
  return_rate_percent: "نسبة المرتجعات %",
  customers: "العملاء",
  stock_value: "قيمة المخزون",
  balance: "الرصيد",
  balance_due: "المستحق",
  total: "الإجمالي",
  total_sales: "إجمالي المبيعات",
  orders_count: "عدد الطلبات",
  collected_cash: "النقد المحصّل",
  remaining_receivable: "متبقٍ آجل",
  total_receivables: "إجمالي الذمم",
  customers_with_debt: "عملاء عليهم دين",
  name: "الاسم",
  customer: "العميل",
  supplier: "المورد",
  phone: "الهاتف",
  date: "التاريخ",
  due_date: "تاريخ الاستحقاق",
  days_late: "أيام التأخير",
  days_overdue: "أيام التأخير",
  days: "الأيام",
  status: "الحالة",
  invoice_no: "رقم الفاتورة",
  sku: "الرمز",
  current_stock: "الرصيد",
  selling_price: "سعر البيع",
  credit: "المبلغ",
  label: "البند",
  last_sale: "آخر بيع",
  created_at: "التاريخ",
};
const MONEY =
  /(amount|total|balance|paid|remaining|sales|price|cost|value|profit|debt|receivable|collected|expenses|returns|credit|due|overdue|cogs|purchases)/;
const NOT_MONEY =
  /(count|invoices|orders|qty|quantity|days|percent|rate|sequence|customers|_id$|^id$|stock$)/;
const HIDDEN =
  /(^id$|_id$|revision|image|url|cursor|scope|note|basis|currency|branch|period|^from$|^to$|by$|as_of)/;
export const isMoney = (key: string) => MONEY.test(key) && !NOT_MONEY.test(key);
export const labelOf = (key: string) => LABELS[key] ?? key.replace(/_/g, " ");
const record = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function scalarKpis(data: Record<string, unknown>): Kpi[] {
  const sources = [data, ...["totals", "metrics"].map((k) => data[k]).filter(record)];
  return sources
    .flatMap((source) => Object.entries(source))
    .filter(([key, value]) => num(value) && !HIDDEN.test(key))
    .map(([key, value]) => ({ key, label: labelOf(key), value: value as number, money: isMoney(key) }));
}
function barGroups(data: Record<string, unknown>, used: Set<unknown>): BarGroup[] {
  const groups: BarGroup[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (!Array.isArray(value) || !value.length || !value.every(record)) continue;
    const rows = value as Record<string, unknown>[];
    const valueKey = ["amount", "value", "total"].find((k) => rows.every((r) => num(r[k])));
    const labelKey = ["label", "name", "customer", "supplier"].find((k) =>
      rows.every((r) => typeof r[k] === "string"),
    );
    // Rows that identify records belong in the table, not in a chart.
    if (
      !valueKey ||
      !labelKey ||
      rows.some((r) => Object.keys(r).some((k) => /_id$/.test(k) && k !== "supplier_id"))
    )
      continue;
    used.add(value);
    groups.push({
      title: labelOf(key === "rows" ? "المبيعات" : key),
      items: rows.slice(0, 10).map((r) => ({
        label: String(r[labelKey]),
        value: r[valueKey] as number,
        money: isMoney(valueKey),
      })),
    });
  }
  return groups;
}
function tableOf(data: unknown, used: Set<unknown>): SourceTable | null {
  let rows = rowsFromData(data);
  if (!rows.length && record(data))
    rows =
      (Object.values(data).find(
        (v) => Array.isArray(v) && v.length && v.every(record) && !used.has(v),
      ) as Record<string, unknown>[]) ?? [];
  if (!rows.length) return null;
  const keys: string[] = [];
  for (const row of rows.slice(0, 5))
    for (const [key, value] of Object.entries(row))
      if (!keys.includes(key) && !HIDDEN.test(key) && (typeof value === "string" || num(value)))
        keys.push(key);
  if (!keys.length) return null;
  return {
    columns: keys.slice(0, 6).map((key) => ({ key, label: labelOf(key), money: isMoney(key) })),
    rows: rows.slice(0, 12),
  };
}
export function buildSourceModel(data: unknown): SourceModel {
  if (!record(data)) return { kpis: [], bars: [], table: tableOf(data, new Set()) };
  let kpis: Kpi[];
  if (record(data.current) && record(data.previous)) {
    const previous = data.previous,
      change = record(data.change_percent) ? data.change_percent : {};
    kpis = scalarKpis(data.current).map((kpi) => ({
      ...kpi,
      ...(num(previous[kpi.key]) ? { previous: previous[kpi.key] as number } : {}),
      change: num(change[kpi.key]) ? (change[kpi.key] as number) : null,
    }));
  } else kpis = scalarKpis(data);
  const used = new Set<unknown>();
  const bars = barGroups(data, used);
  return { kpis: kpis.slice(0, 9), bars, table: tableOf(data, used) };
}
const cell = (value: unknown) => {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};
/** CSV with a BOM so Excel opens Arabic text correctly. */
export function sourceCsv(title: string, model: SourceModel): string {
  const lines: unknown[][] = [[title]];
  if (model.kpis.length) {
    const compare = model.kpis.some((k) => k.previous !== undefined);
    lines.push([], compare ? ["البند", "القيمة", "الفترة السابقة", "التغير %"] : ["البند", "القيمة"]);
    for (const k of model.kpis)
      lines.push(compare ? [k.label, k.value, k.previous ?? "", k.change ?? ""] : [k.label, k.value]);
  }
  for (const group of model.bars) {
    lines.push([], [group.title], ["البند", "القيمة"]);
    for (const item of group.items) lines.push([item.label, item.value]);
  }
  if (model.table) {
    lines.push(
      [],
      model.table.columns.map((c) => c.label),
    );
    for (const row of model.table.rows) lines.push(model.table.columns.map((c) => row[c.key]));
  }
  return `\ufeff${lines.map((line) => line.map(cell).join(",")).join("\r\n")}`;
}
