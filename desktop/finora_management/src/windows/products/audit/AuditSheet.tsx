import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Bottom sheet on phones; existing FINORA detail-drawer proportions on desktop. */
export function AuditSheet({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  onClose(): void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const panel = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const reduced = useReducedMotion();
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const handle = requestAnimationFrame(() => panel.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("[data-popover]")) {
        event.stopPropagation();
        close.current();
      }
      if (event.key === "Tab" && !document.querySelector("[data-popover]")) {
        const targets = Array.from(
          panel.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex="0"]',
          ) ?? [],
        ).filter((node) => node.getClientRects().length > 0);
        if (!targets.length) {
          event.preventDefault();
          panel.current?.focus();
          return;
        }
        const first = targets[0],
          last = targets[targets.length - 1];
        if (
          event.shiftKey &&
          (document.activeElement === first || document.activeElement === panel.current)
        ) {
          event.preventDefault();
          last?.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last || document.activeElement === panel.current)
        ) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      cancelAnimationFrame(handle);
      window.removeEventListener("keydown", onKey, true);
      previous?.focus();
    };
  }, [open]);
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[80]" data-audit-sheet>
          <button
            type="button"
            tabIndex={-1}
            aria-label="إغلاق لوحة الجرد"
            onClick={onClose}
            className="absolute inset-0 bg-ink/15"
          />
          <motion.section
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            className="glass-solid absolute inset-x-0 bottom-0 flex max-h-[94%] min-h-0 flex-col rounded-t-panel outline-none sm:inset-x-auto sm:inset-y-2 sm:start-2 sm:w-[520px] sm:max-w-[90%] sm:rounded-panel"
            initial={reduced ? false : { opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? undefined : { opacity: 0, y: 16 }}
            transition={{ duration: reduced ? 0 : 0.18 }}
          >
            <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-line sm:hidden" aria-hidden />
            <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
              <h2 className="font-semibold text-ink">{title}</h2>
              <button
                type="button"
                aria-label="إغلاق التفاصيل"
                onClick={onClose}
                className="grid h-10 w-10 place-items-center rounded-control text-ink-soft hover:bg-violet-soft"
              >
                <X size={20} />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
            {footer && <footer className="shrink-0 border-t border-line p-3">{footer}</footer>}
          </motion.section>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
