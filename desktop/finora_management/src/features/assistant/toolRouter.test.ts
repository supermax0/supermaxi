import type { LocalTool } from "@shared/localAssistant";
import type { WindowId } from "@/windows/registry";
import { normalizeArabic, routeTools, wantsDraft } from "./toolRouter";

const NAMES = [
  "search_customer",
  "get_customer",
  "get_customer_balance",
  "get_customer_statement",
  "search_products",
  "get_product",
  "get_product_stock",
  "get_low_stock",
  "search_orders",
  "get_order",
  "get_latest_order",
  "get_daily_sales",
  "get_sales_summary",
  "get_cash_balance",
  "get_receivables_summary",
  "get_payables_summary",
  "search_supplier",
  "get_supplier_balance",
  "get_supplier_statement",
  "get_expenses",
  "get_top_products",
  "get_shipping_dues",
  "search_delivery_agents",
  "get_delivery_agent_reports",
  "get_agent_report",
  "get_pending_agent_reports",
  "get_period_comparison",
  "get_sales_breakdown",
  "get_purchases_summary",
  "get_receivables_aging",
  "get_sales_returns",
  "get_overdue_installments",
  "get_stagnant_products",
  "get_product_movements",
];
const catalog: LocalTool[] = NAMES.map((name) => ({ name, description: name, parameters: {} }));
const route = (
  question: string,
  window: WindowId | null = null,
  recentTools: string[] = [],
  hasRecord = false,
) => routeTools(catalog, { question, window, recentTools, hasRecord }).map((t) => t.name);

it("normalizes Arabic spelling variants before matching", () => {
  expect(normalizeArabic("الأقساطُ المتأخّرة")).toBe("الاقساط المتاخره");
  expect(normalizeArabic("مُشتريات، إلى؟")).toBe("مشتريات الي");
});

it.each([
  ["قارن مبيعات هذا الشهر بالشهر الماضي", "get_period_comparison"],
  ["شكد صافي الربح هالشهر؟", "get_period_comparison"],
  ["قارن مبيعات الفروع هذا الشهر", "get_sales_breakdown"],
  ["ملخص مشتريات هذا الشهر حسب المورد", "get_purchases_summary"],
  ["شنو فواتير الشراء غير المسددة؟", "get_purchases_summary"],
  ["اعرض أعمار ديون العملاء", "get_receivables_aging"],
  ["شنو الأقساط المتأخرة؟", "get_overdue_installments"],
  ["شكد نسبة المرتجعات هذا الشهر؟", "get_sales_returns"],
  ["شنو المنتجات الراكدة من 60 يوم؟", "get_stagnant_products"],
  ["اعرض حركة المنتج شاشة LG", "get_product_movements"],
  ["شنو المنتجات اللي قربت تخلص؟", "get_low_stock"],
  ["شكد رصيد الصندوق؟", "get_cash_balance"],
  ["منو أكثر مورد إلنا مستحقات عنده؟", "get_payables_summary"],
  ["شكد رصيد العميل أحمد؟", "get_customer_balance"],
  ["شنو كشوف المندوبين المعلقة؟", "get_pending_agent_reports"],
])("routes %s to %s", (question, tool) => {
  const picked = route(question);
  expect(picked).toContain(tool);
  expect(picked.length).toBeLessThanOrEqual(7);
});

it("adds the search tool that resolves a name to an ID", () => {
  expect(route("شكد رصيد العميل أحمد؟")).toContain("search_customer");
  expect(route("اعرض حركة المنتج شاشة LG")).toContain("search_products");
});

it("uses the open page and the previous answer for short follow-ups", () => {
  expect(route("شنو وضعه؟", "suppliers", [], true)).toContain("get_supplier_balance");
  expect(route("وكشفه؟", null, ["get_customer_balance"])).toContain("get_customer_statement");
  const summary = route("اعرض ملخص بداية الدوام");
  expect(summary).toEqual(
    expect.arrayContaining(["get_daily_sales", "get_low_stock", "get_overdue_installments"]),
  );
});

it("falls back to search tools when nothing matches", () => {
  expect(route("مرحبا")).toEqual(expect.arrayContaining(["search_customer", "get_daily_sales"]));
});

it("offers draft preparation only for creation requests", () => {
  expect(wantsDraft("جهّز مصروف إيجار 50 ألف")).toBe(true);
  expect(wantsDraft("أضف عميل اسمه علي")).toBe(true);
  expect(wantsDraft("شكد مصاريف هذا الشهر؟")).toBe(false);
});
