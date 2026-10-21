import { useToasts } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { WINDOWS, type WindowId } from "@/windows/registry";

/** Recent error toasts, kept so "explain the error" still works after the toast disappears. */
export interface LoggedError {
  message: string;
  at: number;
  window: WindowId | null;
}
const MAX = 5;
const RECENT_MS = 10 * 60_000;
let errors: LoggedError[] = [];
let seen = new Set<number>();
let started = false;
export function startErrorLog(): () => void {
  if (started) return () => undefined;
  started = true;
  const unsubscribe = useToasts.subscribe((state) => {
    for (const t of state.toasts) {
      if (t.tone !== "error" || seen.has(t.id)) continue;
      seen.add(t.id);
      errors = [
        ...errors,
        { message: t.message.slice(0, 600), at: Date.now(), window: useWindowManager.getState().active },
      ].slice(-MAX);
    }
    if (seen.size > 200) seen = new Set([...seen].slice(-50));
  });
  return () => {
    unsubscribe();
    started = false;
  };
}
export function recentErrors(window: WindowId | null, now = Date.now()): LoggedError[] {
  return errors.filter(
    (e) => now - e.at < RECENT_MS && (!window || e.window === window || e.window === null),
  );
}
export function clearErrorLog() {
  errors = [];
  seen = new Set();
}
/** The question sent to the assistant: the real error text first, then where and when it happened. */
export function diagnosisPrompt(
  page: string,
  visibleAlerts: string[],
  logged: LoggedError[],
  now = Date.now(),
): string {
  const lines = [
    ...visibleAlerts.map((text) => `- ظاهر الآن في الصفحة: ${text}`),
    ...logged
      .slice(-3)
      .reverse()
      .map(
        (e) =>
          `- إشعار خطأ قبل ${Math.max(1, Math.round((now - e.at) / 60_000))} دقيقة${e.window ? ` في ${WINDOWS[e.window].title}` : ""}: ${e.message}`,
      ),
  ];
  if (!lines.length)
    return `اشرح خطوات ${page} والأخطاء الشائعة فيه من الدليل؛ لا يوجد خطأ ظاهر أو مسجل حديثاً.`;
  return `اشرح هذه الأخطاء في ${page} واقترح خطوات تحقق عملية. اذكر السبب المؤكد فقط من نص الخطأ والدليل، وإن احتجت رقماً أو حالة فاقرأها بأداة:\n${lines.join("\n")}`;
}
