import type { LocalTool } from "@shared/localAssistant";
import type { WindowId } from "@/windows/registry";

/**
 * Picks the few FINORA read tools a small local model should see for one question.
 * Scored, not first-match: tool phrases, domain words, the open page and the previous
 * answer each add weight, so "شنو وضعه؟" after a supplier answer still reaches supplier tools.
 */
export function normalizeArabic(text: string): string {
  return text
    .toLowerCase()
    .replace(/[ً-ْٰـ]/g, "")
    .replace(/[أإآٱ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/ؤ/g, "و")
    .replace(/ئ/g, "ي")
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}
type Domain =
  "customer" | "product" | "order" | "sales" | "supplier" | "purchase" | "expense" | "cash" | "agent";
const DOMAIN_WORDS: Record<Domain, string[]> = {
  customer: ["عميل", "عملاء", "زبون", "زباين", "زبائن"],
  product: ["منتج", "مادة", "مواد", "بضاعة", "سلعة", "مخزون", "باركود"],
  order: ["طلب", "اوردر", "فاتورة"],
  sales: ["مبيعات", "بيع", "ربح", "ارباح", "تقرير"],
  supplier: ["مورد", "موردين"],
  purchase: ["مشتريات", "شراء", "مشترى"],
  expense: ["مصروف", "مصاريف", "صرفيات", "نفقات"],
  cash: ["صندوق", "قاصة", "خزينة", "نقد", "كاش"],
  agent: ["مندوب", "مندوبين", "سائق", "نقل", "شحن"],
};
const TOOL_HINTS: Record<string, { domain: Domain; words: string[] }> = {
  search_customer: { domain: "customer", words: ["ابحث عن عميل", "عميل اسمه", "رقم العميل"] },
  get_customer: { domain: "customer", words: ["معلومات العميل", "عنوان العميل", "هاتف العميل"] },
  get_customer_balance: {
    domain: "customer",
    words: ["رصيد", "عليه", "عليها", "باقي عليه", "مطلوب", "دينه"],
  },
  get_customer_statement: {
    domain: "customer",
    words: ["كشف العميل", "كشف حساب", "حركات العميل", "فواتير العميل", "كشف"],
  },
  search_products: { domain: "product", words: ["ابحث عن منتج", "منتج اسمه", "باركود"] },
  get_product: { domain: "product", words: ["سعر", "معلومات المنتج", "ظاهر بالمتجر"] },
  get_product_stock: {
    domain: "product",
    words: ["رصيد المخزون", "بالمخزون", "كمية", "متوفر", "موجود", "كم قطعة"],
  },
  get_low_stock: {
    domain: "product",
    words: ["منخفض", "قربت تخلص", "قرب يخلص", "نفد", "نافد", "خلصت", "الحد الادنى", "نواقص"],
  },
  get_product_movements: {
    domain: "product",
    words: ["حركة المنتج", "حركات المنتج", "حركة", "دخل وطلع", "تاريخ المنتج"],
  },
  get_stagnant_products: {
    domain: "product",
    words: ["راكد", "راكدة", "ما انباع", "ما تنباع", "بطيئة", "ما تتحرك"],
  },
  search_orders: { domain: "order", words: ["طلبات", "ابحث عن طلب", "طلب رقم", "فواتير البيع"] },
  get_order: { domain: "order", words: ["تفاصيل الطلب", "تفاصيل الفاتورة", "مواد الطلب"] },
  get_latest_order: { domain: "order", words: ["اخر طلب", "اخر فاتورة", "احدث طلب"] },
  get_daily_sales: { domain: "sales", words: ["مبيعات اليوم", "اليوم", "دوام", "ملخص"] },
  get_sales_summary: {
    domain: "sales",
    words: ["تقرير المبيعات", "مبيعات الشهر", "مبيعات الاسبوع", "مبيعات امس", "فترة"],
  },
  get_period_comparison: {
    domain: "sales",
    words: [
      "قارن",
      "مقارنه",
      "الشهر الماضي",
      "السنه الماضيه",
      "نمو",
      "زياده",
      "نقصان",
      "ربح",
      "ارباح",
      "صافي",
    ],
  },
  get_sales_breakdown: {
    domain: "sales",
    words: [
      "الفروع",
      "فرع",
      "حسب الموظف",
      "الموظفين",
      "حسب الفئه",
      "نقدي واجل",
      "حسب طريقة الدفع",
      "حسب اليوم",
    ],
  },
  get_top_products: {
    domain: "sales",
    words: ["الاكثر مبيعا", "الاعلى مبيعا", "افضل المنتجات", "الاكثر طلبا"],
  },
  get_sales_returns: { domain: "sales", words: ["مرتجع", "مرتجعات", "راجع", "ارجاع", "نسبة المرتجعات"] },
  get_cash_balance: { domain: "cash", words: ["رصيد الصندوق", "صندوق", "قاصة", "خزينه", "النقد المتوفر"] },
  get_receivables_summary: {
    domain: "customer",
    words: ["ذمم العملاء", "ديون العملاء", "اكثر العملاء دينا", "مستحقات العملاء", "ذمم"],
  },
  get_receivables_aging: {
    domain: "customer",
    words: ["اعمار", "عمر الدين", "ديون قديمه", "متاخره", "متاخر", "اعمار الديون"],
  },
  get_overdue_installments: { domain: "customer", words: ["قسط", "اقساط", "تقسيط", "الاقساط المتاخره"] },
  search_supplier: { domain: "supplier", words: ["ابحث عن مورد", "مورد اسمه", "شركة"] },
  get_supplier_balance: {
    domain: "supplier",
    words: ["رصيد المورد", "وضع المورد", "مستحق", "مستحقات", "النا عنده"],
  },
  get_supplier_statement: { domain: "supplier", words: ["كشف المورد", "حركات المورد", "كشف"] },
  get_payables_summary: {
    domain: "supplier",
    words: ["ذمم الموردين", "ديون الموردين", "اكثر مورد", "المستحق للموردين", "مستحقات"],
  },
  get_purchases_summary: {
    domain: "purchase",
    words: ["مشتريات", "فواتير الشراء", "غير المسدده", "غير مسدده", "ملخص مشتريات"],
  },
  get_expenses: { domain: "expense", words: ["مصاريف", "مصروف", "صرفيات", "نفقات", "حسب الفئه"] },
  get_shipping_dues: { domain: "agent", words: ["شركات النقل", "ذمم النقل", "ذمم شركات"] },
  search_delivery_agents: { domain: "agent", words: ["مندوب", "سائق"] },
  get_delivery_agent_reports: { domain: "agent", words: ["كشوف المندوب", "كشف المندوب", "باقي على المندوب"] },
  get_agent_report: { domain: "agent", words: ["agt"] },
  get_pending_agent_reports: { domain: "agent", words: ["معلقه", "بانتظار التنفيذ", "كشوف المندوبين"] },
};
/** Tools that turn a name into the ID the other tools need. */
const RESOLVERS: Partial<Record<Domain, string>> = {
  customer: "search_customer",
  product: "search_products",
  supplier: "search_supplier",
  agent: "search_delivery_agents",
  order: "search_orders",
};
const NEEDS_ID = /^get_(customer|product|supplier|delivery_agent|order)(?!s)|^get_product_movements$/;
const WINDOW_DOMAIN: Partial<Record<WindowId, Domain>> = {
  customers: "customer",
  products: "product",
  pos: "product",
  orders: "order",
  purchases: "purchase",
  suppliers: "supplier",
  reports: "sales",
  expenses: "expense",
  shipping: "agent",
  finance: "cash",
};
const BUNDLES: { when: RegExp; tools: string[] }[] = [
  {
    when: /ملخص.*(دوام|اليوم)|بدايه الدوام|بداية الدوام/,
    tools: ["get_daily_sales", "get_low_stock", "get_receivables_summary", "get_overdue_installments"],
  },
];
const FOLLOW_UP = /(هذا|هذه|هاي|هذي|نفسه|نفس|وضعه|رصيده|كشفه|حركته|عليه|الها|اله)(\s|$)/;
const WRITE_INTENT = /(جهز|اضف|ضيف|سجل|اعمل|انشي|سوي|مسوده|جديد|افتح فاتوره|اكتب)/;
const normalizedHints = Object.fromEntries(
  Object.entries(TOOL_HINTS).map(([name, hint]) => [
    name,
    { ...hint, words: hint.words.map(normalizeArabic) },
  ]),
);
const normalizedDomains = Object.fromEntries(
  Object.entries(DOMAIN_WORDS).map(([d, words]) => [d, words.map(normalizeArabic)]),
) as Record<Domain, string[]>;
function domainOf(name: string): Domain | undefined {
  return TOOL_HINTS[name]?.domain;
}
export interface RouteInput {
  question: string;
  window: WindowId | null;
  /** Domain-bearing tool names from the latest answer, for follow-up questions. */
  recentTools: string[];
  hasRecord?: boolean;
  limit?: number;
}
export function routeTools(catalog: LocalTool[], input: RouteInput): LocalTool[] {
  const q = ` ${normalizeArabic(input.question)} `;
  const limit = input.limit ?? 7;
  const domains = new Map<Domain, number>();
  for (const [domain, words] of Object.entries(normalizedDomains) as [Domain, string[]][])
    if (words.some((w) => q.includes(w))) domains.set(domain, 2);
  const followUp = FOLLOW_UP.test(q) || q.trim().split(" ").length <= 3;
  if (!domains.size || followUp) {
    for (const name of input.recentTools) {
      const d = domainOf(name);
      if (d) domains.set(d, Math.max(domains.get(d) ?? 0, 1.5));
    }
  }
  const pageDomain = input.window ? WINDOW_DOMAIN[input.window] : undefined;
  // With nothing else to go on, the open page decides; otherwise it only breaks ties.
  if (pageDomain)
    domains.set(
      pageDomain,
      (domains.get(pageDomain) ?? 0) + (domains.size ? 1 : 2) + (input.hasRecord ? 0.5 : 0),
    );
  const bundled = new Set(BUNDLES.filter((b) => b.when.test(q)).flatMap((b) => b.tools));
  const ranked = catalog
    .map((tool) => {
      const hint = normalizedHints[tool.name];
      let score = bundled.has(tool.name) ? 6 : 0;
      for (const word of hint?.words ?? []) if (q.includes(word)) score += word.includes(" ") ? 4 : 3;
      if (hint) score += domains.get(hint.domain) ?? 0;
      return { tool, score };
    })
    .filter((s) => s.score >= 2)
    .sort((a, b) => b.score - a.score)
    .map((s) => s.tool);
  const picked: LocalTool[] = [];
  for (const tool of ranked) {
    if (picked.includes(tool)) continue;
    // A tool that needs an ID is useless without the search that finds it.
    const domain = domainOf(tool.name);
    const resolverName = domain && NEEDS_ID.test(tool.name) ? RESOLVERS[domain] : undefined;
    const resolver =
      resolverName && !picked.some((t) => t.name === resolverName)
        ? catalog.find((t) => t.name === resolverName)
        : undefined;
    if (picked.length + (resolver ? 2 : 1) > limit) continue;
    picked.push(tool);
    if (resolver) picked.push(resolver);
  }
  if (picked.length) return picked;
  return catalog.filter((t) => t.name.startsWith("search_") || t.name === "get_daily_sales").slice(0, limit);
}
/** Draft preparation is offered only when the user asks to create something. */
export function wantsDraft(question: string): boolean {
  return WRITE_INTENT.test(normalizeArabic(question));
}
