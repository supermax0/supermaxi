import { formatNumber } from "@/utils/format";
import type { WindowId } from "@/windows/registry";
import { currentAssistantScope, getAssistantTools, readAssistantTool } from "./engine";

/**
 * Proactive checks shown when the panel opens. They call FINORA read tools directly
 * (no language model), only those the user's permissions expose, and are cached per scope.
 */
export interface AssistantAlert {
  id: string;
  level: "warning" | "info";
  text: string;
  /** Follow-up question sent to the assistant when the alert is clicked. */
  question: string;
  window?: WindowId;
}
type Check = {
  tool: string;
  args: Record<string, unknown>;
  read(data: Record<string, unknown>): Omit<AssistantAlert, "id"> | null;
};
const n = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const iqd = (v: number) => `${formatNumber(v)} د.ع`;
export const ALERT_CHECKS: Check[] = [
  {
    tool: "get_low_stock",
    args: { limit: 40 },
    read: (d) =>
      n(d.count)
        ? {
            level: "warning",
            text: `${n(d.count) >= 40 ? "40+" : n(d.count)} منتج وصل للحد الأدنى أو نفد`,
            question: "شنو المنتجات اللي قربت تخلص؟",
            window: "products",
          }
        : null,
  },
  {
    tool: "get_overdue_installments",
    args: { limit: 1 },
    read: (d) =>
      n(d.count)
        ? {
            level: "warning",
            text: `${n(d.count)} قسط متأخر بمبلغ ${iqd(n(d.amount))}`,
            question: "شنو الأقساط المتأخرة؟",
            window: "customers",
          }
        : null,
  },
  {
    tool: "get_pending_agent_reports",
    args: { limit: 20 },
    read: (d) =>
      n(d.count)
        ? {
            level: "info",
            text: `${n(d.count) >= 20 ? "20+" : n(d.count)} كشف مندوب بانتظار التنفيذ`,
            question: "شنو كشوف المندوبين المعلقة؟",
            window: "shipping",
          }
        : null,
  },
  {
    tool: "get_purchases_summary",
    args: { period: "this_month", unpaid_only: true, limit: 1 },
    read: (d) => {
      const totals = (d.totals ?? {}) as Record<string, unknown>;
      return n(totals.remaining)
        ? {
            level: "info",
            text: `مشتريات هذا الشهر غير المسددة ${iqd(n(totals.remaining))}`,
            question: "شنو فواتير الشراء غير المسددة؟",
            window: "purchases",
          }
        : null;
    },
  },
  {
    tool: "get_expense_anomalies",
    args: { period: "this_month", limit: 3 },
    read: (d) =>
      n(d.count)
        ? {
            level: "warning",
            text: `${n(d.count)} فئة مصاريف أعلى من معدلها هذا الشهر`,
            question: "شنو المصاريف غير الطبيعية هذا الشهر؟",
            window: "expenses",
          }
        : null,
  },
  {
    tool: "get_duplicate_customers",
    args: { limit: 1 },
    read: (d) =>
      n(d.groups_count)
        ? {
            level: "info",
            text: `${n(d.groups_count)} رقم هاتف مسجل لأكثر من عميل`,
            question: "منو العملاء المكررين بنفس الرقم؟",
            window: "customers",
          }
        : null,
  },
];
const cache = new Map<string, { at: number; alerts: AssistantAlert[] }>();
const TTL = 10 * 60_000;
export function clearAlertCache() {
  cache.clear();
}
/** Failed or forbidden checks are skipped silently: alerts are a convenience, not a report. */
export async function loadAssistantAlerts(force = false): Promise<AssistantAlert[]> {
  const scope = currentAssistantScope();
  const hit = cache.get(scope);
  if (!force && hit && Date.now() - hit.at < TTL) return hit.alerts;
  const catalog = await getAssistantTools();
  const available = new Set(catalog.tools.map((t) => t.name));
  const results = await Promise.allSettled(
    ALERT_CHECKS.filter((c) => available.has(c.tool)).map(async (check) => {
      const source = await readAssistantTool(check.tool, check.args, catalog.scope, scope);
      const data =
        source.data && typeof source.data === "object" ? (source.data as Record<string, unknown>) : {};
      const alert = check.read(data);
      return alert ? { id: check.tool, ...alert } : null;
    }),
  );
  const alerts = results
    .flatMap((r) => (r.status === "fulfilled" && r.value ? [r.value] : []))
    .sort((a, b) => Number(b.level === "warning") - Number(a.level === "warning"));
  if (scope === currentAssistantScope()) cache.set(scope, { at: Date.now(), alerts });
  return alerts;
}
