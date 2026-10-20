import { AnimatePresence, motion } from "framer-motion";
import { Check } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/utils/cn";

interface DialogShellProps {
  open: boolean;
  title: string;
  onClose(): void;
  children: ReactNode;
  footer: ReactNode;
}

export function DialogShell({ open, title, onClose, children, footer }: DialogShellProps) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    const frame = requestAnimationFrame(() =>
      panel.current?.querySelector<HTMLElement>("[data-autofocus], button")?.focus(),
    );
    return () => {
      window.removeEventListener("keydown", onKey, true);
      cancelAnimationFrame(frame);
    };
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/15"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.12 } }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal
            aria-label={title}
            dir="rtl"
            className="glass-solid w-[420px] rounded-panel p-6"
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
          >
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            <div className="mt-3">{children}</div>
            <div className="mt-6 flex justify-end gap-2">{footer}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

const secondary = "h-10 rounded-control px-4 text-sm text-ink-soft hover:bg-surface-sunken";
const primary =
  "h-10 rounded-control bg-gradient-to-l from-violet to-violet-deep px-5 text-sm font-semibold text-white shadow-control disabled:opacity-50";
const danger =
  "h-10 rounded-control bg-danger px-5 text-sm font-semibold text-white shadow-control disabled:opacity-50";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  tone?: "primary" | "danger";
  busy?: boolean;
  onConfirm(): void;
  onClose(): void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  tone = "primary",
  busy,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  return (
    <DialogShell
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className={secondary} onClick={onClose}>
            تراجع
          </button>
          <button
            type="button"
            data-autofocus
            className={tone === "danger" ? danger : primary}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "جارٍ التنفيذ…" : confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm leading-6 text-ink-soft">{message}</div>
    </DialogShell>
  );
}

export interface PickerOption {
  value: string;
  label: string;
  hint?: string;
}

interface PickerDialogProps {
  open: boolean;
  title: string;
  description?: string;
  options: PickerOption[];
  confirmLabel: string;
  busy?: boolean;
  onConfirm(value: string): void;
  onClose(): void;
}

/** Choose one value (status, shipping company, agent, branch) then confirm. */
export function PickerDialog({
  open,
  title,
  description,
  options,
  confirmLabel,
  busy,
  onConfirm,
  onClose,
}: PickerDialogProps) {
  const [value, setValue] = useState<string | null>(null);
  useEffect(() => {
    if (open) setValue(null);
  }, [open]);

  return (
    <DialogShell
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className={secondary} onClick={onClose}>
            تراجع
          </button>
          <button
            type="button"
            className={primary}
            disabled={value === null || busy}
            onClick={() => value !== null && onConfirm(value)}
          >
            {busy ? "جارٍ التنفيذ…" : confirmLabel}
          </button>
        </>
      }
    >
      {description && <p className="mb-3 text-sm text-ink-soft">{description}</p>}
      <div role="radiogroup" aria-label={title} className="max-h-[300px] space-y-1 overflow-y-auto">
        {options.length === 0 && <p className="py-4 text-center text-sm text-ink-faint">لا توجد خيارات</p>}
        {options.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setValue(option.value)}
              className={cn(
                "flex h-11 w-full items-center gap-3 rounded-control px-3 text-start text-sm transition-colors",
                active
                  ? "bg-violet-soft text-violet-deep ring-1 ring-violet/20"
                  : "text-ink hover:bg-surface-sunken",
              )}
            >
              <span
                className={cn(
                  "grid h-5 w-5 place-items-center rounded-full border",
                  active ? "border-violet bg-violet text-white" : "border-line",
                )}
              >
                {active && <Check size={12} strokeWidth={3} />}
              </span>
              <span className="flex-1">{option.label}</span>
              {option.hint && <span className="text-xs text-ink-faint">{option.hint}</span>}
            </button>
          );
        })}
      </div>
    </DialogShell>
  );
}
