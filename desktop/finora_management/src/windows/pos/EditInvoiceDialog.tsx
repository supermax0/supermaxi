import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { finora, toFinoraError } from "@/api/finora";
import { lineKey, useCart, type CartLine } from "@/features/pos/cart";
import { toast } from "@/stores/toasts";

/** Loads an existing FINORA order into the cart; checkout then saves it through the same POS service (order_id). */
export function EditInvoiceDialog({ open, onClose }: { open: boolean; onClose(): void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const loadForEdit = useCart((s) => s.loadForEdit);

  useLayoutEffect(() => {
    if (!open) return;
    setText("");
    setError(null);
    const frame = requestAnimationFrame(() => input.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopImmediatePropagation();
        close.current();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  const load = useMutation({
    mutationFn: (id: number) => finora.orders.details(id),
    onSuccess: (details) => {
      const { order, items } = details;
      if (!order.customer_id) {
        setError("هذا الطلب لا يحتوي على زبون قابل للتعديل.");
        return;
      }
      const lines: CartLine[] = items
        .filter((item) => item.product_id)
        .map((item) => {
          const productId = item.product_id ?? 0;
          const color = item.variant_color ?? "";
          const saleMode = item.sale_mode === "exchange" ? "exchange" : "normal";
          return {
            key: lineKey(productId, color, saleMode),
            productId,
            name: item.name ?? "",
            detail: color,
            imageUrl: "",
            color,
            saleMode,
            unitPrice: item.price ?? 0,
            qty: item.qty,
            available: Number.POSITIVE_INFINITY,
            storageSource: item.storage_source ?? undefined,
          };
        });
      loadForEdit(
        order.id,
        {
          id: order.customer_id,
          name: order.customer ?? "",
          phone: order.phone ?? "",
          city: order.city ?? "",
          address: order.address ?? "",
          blacklisted: false,
          blacklist_message: "",
        },
        lines,
        order.discount_amount ?? 0,
      );
      toast.info(`تم تحميل الطلب #${order.id} للتعديل`);
      onClose();
    },
    onError: (failure) => setError(toFinoraError(failure).message),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const id = Number(text.replace(/[^\d]/g, ""));
    if (!id) return setError("أدخل رقم الطلب");
    load.mutate(id);
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[90] grid place-items-center bg-ink/15"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.form
            onSubmit={submit}
            role="dialog"
            aria-modal
            aria-label="تعديل فاتورة"
            dir="rtl"
            className="glass-solid w-[380px] rounded-panel p-6"
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6 }}
          >
            <h2 className="text-base font-semibold text-ink">تعديل فاتورة</h2>
            <p className="mt-1 text-sm text-ink-soft">أدخل رقم الطلب لتحميله في السلة.</p>
            <input
              ref={input}
              dir="ltr"
              inputMode="numeric"
              aria-label="رقم الطلب"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="#10045"
              className="ltr-isolate mt-4 h-12 w-full rounded-control border border-line bg-white px-4 text-lg outline-none focus:border-violet/45"
            />
            {error && (
              <p role="alert" className="mt-3 text-sm text-danger">
                {error}
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="h-10 rounded-control px-4 text-sm text-ink-soft hover:bg-surface-sunken"
              >
                تراجع
              </button>
              <button
                type="submit"
                disabled={load.isPending}
                className="h-10 rounded-control bg-gradient-to-l from-violet to-violet-deep px-5 text-sm font-semibold text-white disabled:opacity-50"
              >
                {load.isPending ? "جارٍ التحميل…" : "تحميل"}
              </button>
            </div>
          </motion.form>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
