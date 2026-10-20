import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useLayoutEffect, type ReactNode } from "react";
import { useAssistant } from "@/features/assistant/state";
import { IconButton } from "./IconButton";

interface SidePanelProps {
  open: boolean;
  title: string;
  subtitle?: ReactNode;
  onClose(): void;
  actions?: ReactNode;
  /** Pinned action bar under the scrolling body. */
  footer?: ReactNode;
  layer?: number;
  children: ReactNode;
}

/** Detail drawer that slides in over the table from the window's start edge (right in RTL). */
export function SidePanel({
  open,
  title,
  subtitle,
  onClose,
  actions,
  footer,
  children,
  layer = 30,
}: SidePanelProps) {
  useLayoutEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      // Help and other floating controls take Escape before their containing panel.
      if (
        event.key === "Escape" &&
        !useAssistant.getState().open &&
        !useAssistant.getState().training &&
        !document.querySelector('[aria-modal="true"], [role="menu"], [data-popover]')
      ) {
        event.stopImmediatePropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          role="complementary"
          aria-label={title}
          className="glass-solid absolute inset-y-3 start-3 z-30 flex w-[440px] max-w-[calc(100%-1.5rem)] flex-col rounded-panel sm:max-w-[60%]"
          initial={{ opacity: 0, x: 40 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 30, transition: { duration: 0.16 } }}
          transition={{ type: "spring", stiffness: 420, damping: 38 }}
          style={{ willChange: "transform, opacity", zIndex: layer }}
        >
          <header className="flex items-start gap-3 border-b border-line/70 px-5 py-4">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-base font-semibold text-ink">{title}</h2>
              {subtitle && <div className="mt-1 text-xs text-ink-soft">{subtitle}</div>}
            </div>
            {actions}
            <IconButton label="إغلاق التفاصيل" size="sm" onClick={onClose}>
              <X size={16} />
            </IconButton>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="border-t border-line/70 px-4 py-3">{footer}</footer>}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/50 py-2.5 text-sm last:border-0">
      <span className="shrink-0 text-ink-soft">{label}</span>
      <span className="min-w-0 text-end text-ink">{children}</span>
    </div>
  );
}
