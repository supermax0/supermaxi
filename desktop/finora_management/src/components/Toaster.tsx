import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Info, X, XCircle, type LucideIcon } from "lucide-react";
import { useToasts, type ToastTone } from "@/stores/toasts";
import { cn } from "@/utils/cn";

const TONES: Record<ToastTone, { icon: LucideIcon; className: string }> = {
  success: { icon: CheckCircle2, className: "text-success" },
  error: { icon: XCircle, className: "text-danger" },
  info: { icon: Info, className: "text-azure" },
};

/** Small, non-blocking feedback after operations (never a modal for success). */
export function Toaster() {
  const toasts = useToasts((s) => s.toasts);
  const dismiss = useToasts((s) => s.dismiss);

  return (
    <div
      className="pointer-events-none fixed bottom-6 start-6 z-[70] flex w-[360px] flex-col gap-2"
      aria-live="polite"
    >
      <AnimatePresence initial={false}>
        {toasts.map((item) => {
          const tone = TONES[item.tone];
          const Icon = tone.icon;
          return (
            <motion.div
              key={item.id}
              layout
              role={item.tone === "error" ? "alert" : "status"}
              className="glass-solid pointer-events-auto flex items-start gap-3 rounded-control px-4 py-3"
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24, transition: { duration: 0.16 } }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            >
              <Icon size={18} className={cn("mt-0.5 shrink-0", tone.className)} aria-hidden />
              <p className="flex-1 text-sm leading-6 text-ink">{item.message}</p>
              <button
                type="button"
                aria-label="إخفاء"
                onClick={() => dismiss(item.id)}
                className="text-ink-faint hover:text-ink"
              >
                <X size={15} />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
