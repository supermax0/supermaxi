import { ArrowDown, ArrowUp } from "lucide-react";
import { useState } from "react";
import { DialogShell, ConfirmDialog } from "@/components/Dialog";
import { toast } from "@/stores/toasts";
import { useAvailableWindows } from "@/hooks/useAvailableWindows";
import { WINDOWS } from "@/windows/registry";
import { actionAllowed } from "./navigation";
import {
  ACTIONS,
  WIDGETS,
  defaultPreferences,
  useWorkspace,
  type ActionId,
  type WidgetId,
  type WorkspacePreferences,
} from "./state";

export const ACTION_LABELS: Record<ActionId, string> = {
  order: "إضافة طلب",
  sale: "بيع جديد",
  expense: "إضافة مصروف",
  receipt: "سند قبض",
  audit: "جرد سريع",
  search: "بحث شامل",
  product: "منتج جديد",
  customer: "عميل جديد",
};
const LABELS: Record<WidgetId, string> = {
  sales: "مبيعات اليوم",
  orders: "الطلبات",
  attention: "المتابعة",
  receivables: "المستحقات",
  quick: "ابدأ العمل",
  tasks: "يحتاج اهتمامك",
  resume: "أكمل من حيث توقفت",
  activity: "النشاط الأخير",
  assistant: "المساعد الذكي (عند توفره)",
};
const button = "workspace-button";
function move<T>(items: T[], item: T, direction: number): T[] {
  const next = [...items],
    at = next.indexOf(item),
    other = at + direction;
  const current = next[at],
    neighbor = next[other];
  if (at >= 0 && other >= 0 && other < next.length && current !== undefined && neighbor !== undefined)
    [next[at], next[other]] = [neighbor, current];
  return next;
}
export function WorkspaceCustomization({ onClose }: { onClose(): void }) {
  const prefs = useWorkspace((s) => s.prefs);
  const [draft, setDraft] = useState<WorkspacePreferences>(() => ({
    ...prefs,
    actions: [...prefs.actions],
    visible: [...prefs.visible],
    order: [...prefs.order],
  }));
  const [resetting, setResetting] = useState(false);
  const available = useAvailableWindows();
  const order = [...new Set([...draft.order, ...WIDGETS])];
  return (
    <>
      <DialogShell
        open
        title="تخصيص مساحة العمل"
        onClose={onClose}
        footer={
          <>
            <button className={button} onClick={onClose}>
              إلغاء
            </button>
            <button
              className={`${button} workspace-primary`}
              onClick={() => {
                if (!useWorkspace.getState().configure(draft)) {
                  toast.error("تعذر حفظ التخصيص على هذا الجهاز؛ لم تتغير إعداداتك");
                  return;
                }
                toast.success("تم حفظ مساحة العمل");
                const scope = document.activeElement?.closest('[role="dialog"]');
                if (scope) document.dispatchEvent(new CustomEvent("finora:form-saved", { detail: scope }));
                onClose();
              }}
            >
              حفظ التخصيص
            </button>
          </>
        }
      >
        <div className="workspace-customization">
          <fieldset>
            <legend>حجم الواجهة</legend>
            <div className="flex gap-2">
              {([false, true] as const).map((compact) => (
                <button
                  key={String(compact)}
                  className={`${button} ${draft.compact === compact ? "workspace-selected" : ""}`}
                  aria-pressed={draft.compact === compact}
                  onClick={() => setDraft({ ...draft, compact })}
                >
                  {compact ? "مضغوط" : "مريح"}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend>البطاقات والأقسام</legend>
            <p>الترتيب داخل كل صف يحافظ على تناسق التصميم.</p>
            {order.map((id, i) => (
              <div key={id} className="workspace-setting-row">
                <label>
                  <input
                    type="checkbox"
                    checked={draft.visible.includes(id)}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        visible: e.target.checked
                          ? [...draft.visible, id]
                          : draft.visible.filter((x) => x !== id),
                      })
                    }
                  />
                  {LABELS[id]}
                </label>
                <div>
                  <button
                    aria-label={`تقديم ${LABELS[id]}`}
                    disabled={i === 0}
                    onClick={() => setDraft({ ...draft, order: move(order, id, -1) })}
                  >
                    <ArrowUp size={15} />
                  </button>
                  <button
                    aria-label={`تأخير ${LABELS[id]}`}
                    disabled={i === order.length - 1}
                    onClick={() => setDraft({ ...draft, order: move(order, id, 1) })}
                  >
                    <ArrowDown size={15} />
                  </button>
                </div>
              </div>
            ))}
          </fieldset>
          <fieldset>
            <legend>اختصارات الوصول السريع</legend>
            {[...draft.actions, ...ACTIONS.filter((id) => !draft.actions.includes(id))]
              .filter(actionAllowed)
              .map((id) => (
                <div key={id} className="workspace-setting-row">
                  <label>
                    <input
                      type="checkbox"
                      checked={draft.actions.includes(id)}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          actions: e.target.checked
                            ? [...draft.actions, id]
                            : draft.actions.filter((x) => x !== id),
                        })
                      }
                    />
                    {ACTION_LABELS[id]}
                  </label>
                  <div>
                    <button
                      aria-label={`تقديم ${ACTION_LABELS[id]}`}
                      disabled={draft.actions.indexOf(id) <= 0}
                      onClick={() => setDraft({ ...draft, actions: move(draft.actions, id, -1) })}
                    >
                      <ArrowUp size={15} />
                    </button>
                    <button
                      aria-label={`تأخير ${ACTION_LABELS[id]}`}
                      disabled={
                        !draft.actions.includes(id) || draft.actions.indexOf(id) === draft.actions.length - 1
                      }
                      onClick={() => setDraft({ ...draft, actions: move(draft.actions, id, 1) })}
                    >
                      <ArrowDown size={15} />
                    </button>
                  </div>
                </div>
              ))}
          </fieldset>
          <fieldset>
            <legend>عند فتح التطبيق</legend>
            <label>
              الصفحة الافتراضية
              <select
                value={draft.home}
                onChange={(e) => setDraft({ ...draft, home: e.target.value as WorkspacePreferences["home"] })}
              >
                <option value="workspace">مساحة العمل</option>
                {available.map((id) => (
                  <option key={id} value={id}>
                    {WINDOWS[id].title}
                  </option>
                ))}
              </select>
            </label>
            <label className="workspace-setting-row">
              <span>تذكّر آخر الأعمال والجلسة</span>
              <input
                type="checkbox"
                checked={draft.remember}
                onChange={(e) => setDraft({ ...draft, remember: e.target.checked })}
              />
            </label>
            <label className="workspace-setting-row">
              <span>اقتراح اختصارات من الاستخدام المحلي</span>
              <input
                type="checkbox"
                checked={draft.suggestions}
                onChange={(e) => setDraft({ ...draft, suggestions: e.target.checked })}
              />
            </label>
          </fieldset>
          <button className={button} onClick={() => setResetting(true)}>
            استعادة التصميم الافتراضي
          </button>
        </div>
      </DialogShell>
      <ConfirmDialog
        open={resetting}
        title="استعادة التصميم الافتراضي"
        message="سيُعاد ترتيب بطاقات الرئيسية واختصاراتها. تبقى بيانات العمل محفوظة."
        confirmLabel="استعادة"
        onClose={() => setResetting(false)}
        onConfirm={() => {
          setDraft(defaultPreferences());
          setResetting(false);
        }}
      />
    </>
  );
}
