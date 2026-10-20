import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, GraduationCap, X } from "lucide-react";
import { allowedWindow } from "@/features/workspace/state";
import { openWorkspaceTarget, runWorkspaceAction } from "@/features/workspace/navigation";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import { GUIDES, normalizeArabic, type Guide, type GuideStep } from "./catalog";
import { currentAssistantScope } from "./engine";
import { useAssistant } from "./state";

const progressKey = () => `finora:training:v1:${currentAssistantScope()}`;
export function trainingProgress(): Record<string, number> {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(progressKey()) ?? "{}");
    return raw && typeof raw === "object"
      ? Object.fromEntries(
          Object.entries(raw).filter(
            ([key, value]) =>
              GUIDES.some((g) => g.id === key) &&
              typeof value === "number" &&
              Number.isInteger(value) &&
              value >= 0 &&
              value <= 12,
          ),
        )
      : {};
  } catch {
    return {};
  }
}
function saveProgress(id: string, step: number) {
  try {
    localStorage.setItem(progressKey(), JSON.stringify({ ...trainingProgress(), [id]: step }));
  } catch {
    toast.info("التقدم متاح في الجلسة الحالية؛ تعذر حفظه على الجهاز");
  }
}
export function startTraining(guide: Guide) {
  if (!allowedWindow(guide.window, useSession.getState().session)) {
    toast.error("الدليل يحتاج صلاحية فتح القسم");
    return;
  }
  const at = Math.min(trainingProgress()[guide.id] ?? 0, guide.steps.length - 1);
  openWorkspaceTarget({ window: guide.window });
  useAssistant.setState({ training: { id: guide.id, step: Math.max(0, at) }, open: false });
}
function findElement(guide: Guide, step: GuideStep): HTMLElement | null {
  const root = document.querySelector(`[data-window="${guide.window}"]`);
  const visible = (node: Element) =>
    !!(node as HTMLElement).getClientRects().length &&
    getComputedStyle(node).visibility !== "hidden" &&
    !node.closest('[aria-hidden="true"]');
  if (step.button && root)
    return (
      Array.from(root.querySelectorAll<HTMLElement>("button")).find(
        (e) =>
          visible(e) && normalizeArabic(e.textContent ?? "").includes(normalizeArabic(step.button ?? "")),
      ) ?? null
    );
  if (step.field) {
    const containers = [
      ...document.querySelectorAll('[role="dialog"][aria-modal="true"], [role="dialog"]'),
      ...(root ? [root] : []),
    ].filter(visible);
    for (const container of containers) {
      const exact = Array.from(container.querySelectorAll<HTMLElement>("input,select,textarea")).find(
        (e) =>
          visible(e) &&
          normalizeArabic(e.getAttribute("aria-label") ?? "").includes(normalizeArabic(step.field ?? "")),
      );
      if (exact) return exact;
      const label = Array.from(container.querySelectorAll("label")).find((e) =>
        normalizeArabic(e.textContent ?? "").includes(normalizeArabic(step.field ?? "")),
      );
      if (label) {
        const field =
          label.querySelector<HTMLElement>("input,select,textarea") ||
          (label.htmlFor ? document.getElementById(label.htmlFor) : null);
        if (field && visible(field)) return field;
      }
    }
  }
  return null;
}
export function TrainingOverlay() {
  const training = useAssistant((s) => s.training);
  const active = useWindowManager((s) => s.active);
  const [rect, setRect] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const guide = GUIDES.find((g) => g.id === training?.id),
    step = guide?.steps[training?.step ?? 0];
  useEffect(() => {
    if (!guide || !step) {
      setRect(null);
      return;
    }
    const update = () => {
      if (active !== guide.window) {
        setRect(null);
        return;
      }
      const element = findElement(guide, step);
      const r = element?.getBoundingClientRect();
      setRect(r && r.width && r.height ? { x: r.x, y: r.y, width: r.width, height: r.height } : null);
    };
    update();
    const timer = window.setInterval(update, 350);
    window.addEventListener("resize", update);
    return () => {
      clearInterval(timer);
      window.removeEventListener("resize", update);
    };
  }, [guide, step, active]);
  if (!training || !guide || !step || !allowedWindow(guide.window, useSession.getState().session))
    return null;
  const last = training.step === guide.steps.length - 1;
  return createPortal(
    <div className="finora-training-layer" dir="rtl">
      {rect && (
        <div
          aria-hidden
          className="finora-training-highlight"
          style={{
            left: Math.max(0, rect.x - 4),
            top: Math.max(0, rect.y - 4),
            width: rect.width + 8,
            height: rect.height + 8,
          }}
        />
      )}
      <section aria-label="التعليم التفاعلي" className="finora-training-card">
        <header>
          <GraduationCap size={19} />
          <strong>{guide.title}</strong>
          <button aria-label="إيقاف التعليم" onClick={() => useAssistant.setState({ training: null })}>
            <X size={18} />
          </button>
        </header>
        <small>
          خطوة {training.step + 1} من {guide.steps.length} · شرح ومراجعة
        </small>
        <h3>{step.title}</h3>
        <p>{step.text}</p>
        {(step.button || step.field) && (
          <p className="assistant-muted">
            {rect
              ? "العنصر المقصود محدد على الشاشة."
              : "اتبع شرح الخطوة داخل القسم؛ التحديد يظهر عند توفر العنصر في النموذج المفتوح."}
          </p>
        )}
        <footer>
          {active !== guide.window && (
            <button
              className="workspace-button"
              onClick={() => openWorkspaceTarget({ window: guide.window })}
            >
              فتح القسم
            </button>
          )}
          {step.action && (
            <button
              className="workspace-button"
              onClick={() => {
                if (document.querySelector('[role="dialog"][aria-modal="true"]')) {
                  toast.info("أكمل النموذج المفتوح أو أغلقه أولاً");
                  return;
                }
                runWorkspaceAction(step.action ?? "search");
              }}
            >
              فتح النموذج
            </button>
          )}
          {training.step > 0 && (
            <button
              className="workspace-button"
              onClick={() => useAssistant.setState({ training: { ...training, step: training.step - 1 } })}
            >
              السابق
            </button>
          )}
          <button
            className="workspace-button workspace-primary"
            onClick={() => {
              saveProgress(guide.id, training.step + 1);
              useAssistant.setState({ training: last ? null : { ...training, step: training.step + 1 } });
              if (last) toast.success("اكتمل الدليل. العمليات تحفظ من نماذجها الأصلية بعد مراجعتك.");
            }}
          >
            {last ? "إنهاء الدليل" : "فهمت، التالي"}
            <ChevronLeft size={15} />
          </button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
