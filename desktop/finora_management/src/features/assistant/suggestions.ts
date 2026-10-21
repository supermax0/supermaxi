import type { WindowId } from "@/windows/registry";
import type { AssistantPageDetails } from "./pageContext";

export interface AssistantSuggestion {
  text: string;
  /** Opens the guided lesson tab instead of sending a question. */
  learn?: boolean;
}
const ask = (text: string): AssistantSuggestion => ({ text });
const HOME: AssistantSuggestion[] = [
  ask("اعرض ملخص بداية الدوام"),
  ask("قارن مبيعات هذا الشهر بالشهر الماضي"),
  ask("شنو الأقساط المتأخرة؟"),
  { text: "علّمني أضيف منتج", learn: true },
];
const BY_WINDOW: Partial<Record<WindowId, AssistantSuggestion[]>> = {
  suppliers: [
    ask("منو أكثر مورد إلنا مستحقات عنده؟"),
    ask("ملخص مشتريات هذا الشهر حسب المورد"),
    ask("شنو فواتير الشراء غير المسددة؟"),
    { text: "علّمني أسجل شراء", learn: true },
  ],
  customers: [
    ask("اعرض أعمار ديون العملاء"),
    ask("شنو الأقساط المتأخرة؟"),
    ask("منو أكثر العملاء ديناً؟"),
    { text: "علّمني أضيف عميل", learn: true },
  ],
  products: [
    ask("شنو المنتجات اللي قربت تخلص؟"),
    ask("شنو المنتجات الراكدة من 60 يوم؟"),
    ask("ليش المنتج ما ظاهر بالمتجر؟"),
    { text: "علّمني أضيف منتج", learn: true },
  ],
  orders: [ask("شكد مبيعات اليوم؟"), ask("اعرض آخر طلب"), ask("شكد نسبة المرتجعات هذا الشهر؟")],
  purchases: [
    ask("ملخص مشتريات هذا الشهر"),
    ask("شنو فواتير الشراء غير المسددة؟"),
    { text: "علّمني أسجل شراء", learn: true },
  ],
  expenses: [
    ask("شكد مصاريف هذا الشهر حسب الفئة؟"),
    ask("قارن مصاريف هذا الشهر بالشهر الماضي"),
    { text: "علّمني أسجل مصروف", learn: true },
  ],
  reports: [
    ask("قارن مبيعات هذا الشهر بالشهر الماضي"),
    ask("قارن مبيعات الفروع هذا الشهر"),
    ask("شنو المنتجات الأكثر مبيعاً هذا الشهر؟"),
  ],
  pos: [ask("شكد مبيعات اليوم؟"), ask("شنو المنتجات اللي قربت تخلص؟"), { text: "علّمني أبيع", learn: true }],
  shipping: [ask("شنو كشوف المندوبين المعلقة؟"), ask("شكد ذمم شركات النقل؟")],
  finance: [ask("شكد رصيد الصندوق؟"), ask("اعرض أعمار ديون العملاء")],
};
/** Record-specific questions first: they answer "this" without the user retyping a name. */
function recordSuggestions(window: WindowId, name: string): AssistantSuggestion[] {
  switch (window) {
    case "suppliers":
      return [ask(`شنو وضع المورد ${name}؟`), ask(`اعرض كشف المورد ${name}`)];
    case "customers":
      return [ask(`شكد رصيد العميل ${name}؟`), ask(`اعرض كشف العميل ${name}`)];
    case "products":
      return [ask(`شكد رصيد ${name} بالمخزون؟`), ask(`اعرض حركة المنتج ${name}`)];
    case "orders":
      return [ask(`اعرض تفاصيل الطلب ${name}`)];
    default:
      return [];
  }
}
export function assistantSuggestions(
  window: WindowId | null,
  details: AssistantPageDetails | undefined,
): AssistantSuggestion[] {
  const base = (window && BY_WINDOW[window]) || HOME;
  const record = window && details?.record ? recordSuggestions(window, details.record.name) : [];
  return [...record, ...base].slice(0, 4);
}
