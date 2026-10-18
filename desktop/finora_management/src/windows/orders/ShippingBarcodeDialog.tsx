import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Eye, Loader2, PackageCheck, ScanBarcode, Truck, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { finora, toFinoraError } from "@/api/finora";
import type { OrderRow } from "@/api/finora/orders";
import { useOrderPreferences } from "@/features/orders/orderPreferences";
import {
  initialBarcodes,
  rememberedShippingCompany,
  rememberShippingCompany,
  shippingBarcodeProblem,
  shippingSlots,
} from "@/features/orders/shippingBarcodes";
import { orderStatusStyle } from "@/features/orders/status";
import {
  orderFailureMessage,
  useOrderDetails,
  useOrderLookups,
  useSaveShippingBarcodes,
} from "@/features/orders/useOrders";
import { scannerChar } from "@/hooks/useBarcodeScanner";
import { cn } from "@/utils/cn";
import { FeatureHelp } from "@/components/FeatureHelp";
import { formatIqd } from "@/utils/money";

/** What was scanned: the order id is known at once when the order is in the loaded table. */
export interface OrderScan {
  code: string;
  orderId: number | null;
  row: OrderRow | null;
  receiptMode?: boolean;
}

interface ShippingBarcodeDialogProps {
  scan: OrderScan | null;
  onClose(): void;
  onShowDetails(orderId: number): void;
}

const PRE_SHIPMENT = new Set(["تم الطلب", "معباة"]);
const PLACEHOLDER_SLOTS = [{ label: "باركود الشحن" }];

/**
 * Opened by scanning an order's barcode. It appears instantly with the
 * barcode field focused; the order's pieces load in the background and the
 * typed/scanned value is kept. Enter moves to the next piece and (if enabled
 * in Settings → الطلبات) saves after the last one.
 */
export function ShippingBarcodeDialog({ scan, onClose, onShowDetails }: ShippingBarcodeDialogProps) {
  const open = scan !== null;
  const preferredAutoSave = useOrderPreferences((s) => s.autoSaveShipping);
  const autoSave = preferredAutoSave && !scan?.receiptMode;
  const [mode, setMode] = useState<"order" | "pieces">("pieces");
  const lookup = useQuery({
    queryKey: ["orders", "barcode", scan?.code ?? ""],
    queryFn: () => finora.orders.findByBarcode(scan?.code ?? ""),
    enabled: open && scan.orderId === null,
    retry: false,
    staleTime: 60_000,
  });
  const orderId = scan?.orderId ?? lookup.data ?? null;
  const row = scan?.row ?? null;
  const details = useOrderDetails(orderId);
  const lookups = useOrderLookups();
  const save = useSaveShippingBarcodes();
  const order = details.data?.order;
  const companies = useMemo(() => lookups.data?.shipping_companies ?? [], [lookups.data]);
  const slots = useMemo(
    () =>
      mode === "order"
        ? [{ label: "رقم الوصل / البوليصة" }]
        : details.data
          ? shippingSlots(details.data.items)
          : PLACEHOLDER_SLOTS,
    [details.data, mode],
  );

  const [companyId, setCompanyId] = useState<number | null>(null);
  const [barcodes, setBarcodes] = useState<string[]>([""]);
  const [error, setError] = useState<string | null>(null);
  const [submitRequested, setSubmitRequested] = useState(false);
  const inputs = useRef<Array<HTMLInputElement | null>>([]);
  const saveButton = useRef<HTMLButtonElement>(null);
  const filledFor = useRef<string | null>(null);
  const filledKey = order ? `${order.id}:${mode}:${slots.length}` : null;
  const companyTouched = useRef(false);

  // every scan starts clean, with the field ready for the shipping barcode
  useEffect(() => {
    if (!scan) return;
    filledFor.current = null;
    detectedFor.current = null;
    companyTouched.current = false;
    setBarcodes([""]);
    setCompanyId(null);
    setError(null);
    setSubmitRequested(false);
    setMode(scan.receiptMode ? "order" : "pieces");
    requestAnimationFrame(() => inputs.current[0]?.focus());
  }, [scan]);

  const detectedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!order || detectedFor.current === order.id) return;
    detectedFor.current = order.id;
    if (scan?.receiptMode && (order.shipping_barcodes?.length ?? 0) > 1) setMode("pieces");
  }, [order, scan]);

  // company: the order's own, else the last one used here, else the only one
  useEffect(() => {
    if (!open || companyTouched.current || companies.length === 0) return;
    const known = (id: number | null | undefined) => (id && companies.some((c) => c.id === id) ? id : null);
    const next =
      known(order?.shipping_company_id) ??
      known(row?.shipping_company_id) ??
      known(rememberedShippingCompany()) ??
      (companies.length === 1 ? (companies[0]?.id ?? null) : null);
    setCompanyId((current) => (order ? (next ?? current) : (current ?? next)));
  }, [open, companies, order, row]);

  // pieces arrive: one field per piece, keeping whatever was already scanned
  useEffect(() => {
    if (!open || !order || !details.data || filledFor.current === filledKey) return;
    filledFor.current = filledKey;
    const saved = initialBarcodes(slots.length, order);
    setBarcodes((typed) => saved.map((value, i) => typed[i]?.trim() || value));
    const active = document.activeElement;
    if (!inputs.current.some((input) => input !== null && input === active && input.value)) {
      requestAnimationFrame(() => {
        const list = inputs.current.slice(0, slots.length);
        (list.find((input) => input && !input.value) ?? list[0])?.focus();
      });
    }
  }, [open, order, details.data, slots.length, filledKey]);

  const problem = shippingBarcodeProblem(companyId, barcodes);
  const locked =
    Boolean(order?.is_stock_locked ?? row?.is_stock_locked) ||
    ["راجع", "راجعة", "مرتجع", "ملغي"].includes((order?.status ?? row?.status ?? "").trim()) ||
    ["راجع", "راجعة", "مرتجع"].includes((order?.payment ?? row?.payment_status ?? "").trim());
  const status = (order?.status ?? row?.status ?? "").trim();
  const willShip = PRE_SHIPMENT.has(status);
  const ready = Boolean(order) && filledFor.current === filledKey;
  const canSave = ready && !locked && !problem && !save.isPending;

  const submit = useCallback(() => {
    if (orderId === null) return;
    if (problem) {
      setError(problem);
      return;
    }
    if (!canSave || companyId === null) return;
    setError(null);
    save.mutate(
      { id: orderId, companyId, barcodes: barcodes.map((b) => b.trim()) },
      {
        onSuccess: () => {
          rememberShippingCompany(companyId);
          onClose();
        },
        onError: (failure) => setError(orderFailureMessage(failure)),
      },
    );
  }, [orderId, problem, canSave, companyId, barcodes, save, onClose]);

  // Enter on the last field before the order finished loading: save once it is in
  useEffect(() => {
    if (!submitRequested || !ready) return;
    setSubmitRequested(false);
    const firstEmpty = inputs.current.slice(0, slots.length).find((input) => input && !input.value);
    if (firstEmpty) firstEmpty.focus();
    else submit();
  }, [submitRequested, ready, slots.length, submit]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        if (!save.isPending) onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose, save.isPending]);

  const setBarcode = (index: number, value: string) =>
    setBarcodes((list) => list.map((b, i) => (i === index ? value : b)));

  const onFieldKey = (index: number) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const next = inputs.current[index + 1];
      if (next && index + 1 < slots.length) next.focus();
      else if (!autoSave) saveButton.current?.focus();
      else if (ready) submit();
      else setSubmitRequested(true);
      return;
    }
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    // A scanner on an Arabic keyboard layout would type Arabic letters: use the physical key.
    const char = scannerChar(event);
    if (!char || event.key === char) return;
    event.preventDefault();
    const input = event.currentTarget;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    setBarcode(index, input.value.slice(0, start) + char + input.value.slice(end));
    requestAnimationFrame(() => input.setSelectionRange(start + 1, start + 1));
  };

  const customer = order?.customer ?? row?.customer_name;
  const city = order?.city ?? row?.city;
  const total = order?.total ?? row?.total;
  const loadError = lookup.error
    ? `لا يوجد طلب بالباركود ${scan?.code ?? ""}`
    : details.error
      ? toFinoraError(details.error).message
      : null;
  const title = orderId !== null ? `#${orderId}` : (scan?.code ?? "");

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/15"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.1 } }}
          transition={{ duration: 0.12 }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget && !save.isPending) onClose();
          }}
        >
          <motion.div
            role="dialog"
            aria-modal
            aria-label={`${scan.receiptMode ? "وصل شركة النقل" : "باركود شركة النقل"} — الطلب ${title}`}
            dir="rtl"
            className="glass-solid flex max-h-[min(720px,92vh)] w-[min(520px,94vw)] flex-col overflow-hidden rounded-panel bg-[#fbfaff]"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4, transition: { duration: 0.1 } }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="flex items-center gap-3 border-b border-line/70 px-5 py-4">
              <span className="grid h-11 w-11 place-items-center rounded-control bg-gradient-to-br from-azure to-violet-deep text-white shadow-control">
                <ScanBarcode size={21} aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="text-[17px] font-bold text-ink">
                  وصل / بوليصة شركة النقل · <span className="ltr-isolate">{title}</span>
                </h2>
                <p className="flex items-center gap-1.5 truncate text-xs text-ink-faint">
                  {customer !== undefined ? (
                    `${customer || "—"} · ${city ?? ""} · ${formatIqd(total ?? 0)}`
                  ) : (
                    <>
                      <Loader2 size={12} className="animate-spin" aria-hidden /> جارٍ البحث عن الطلب…
                    </>
                  )}
                </p>
              </div>
              <button
                type="button"
                aria-label="إغلاق"
                onClick={onClose}
                disabled={save.isPending}
                className="grid h-9 w-9 place-items-center rounded-[10px] text-ink-soft hover:bg-surface-sunken"
              >
                <X size={18} />
              </button>
            </header>

            {loadError ? (
              <p role="alert" className="m-5 rounded-control bg-danger-soft px-4 py-3 text-sm text-danger">
                {loadError}
              </p>
            ) : locked ? (
              <p className="m-5 rounded-control bg-warning-soft px-3.5 py-3 text-sm text-warning">
                هذا الطلب مقفل أو راجع أو ملغي، ولا يمكن تعديل وصل النقل له.
              </p>
            ) : (
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
                <div className="flex h-7 items-center gap-2 text-sm">
                  <span className="text-ink-soft">الحالة:</span>
                  <span className="font-semibold text-ink">
                    {status ? orderStatusStyle(status).label : "…"}
                  </span>
                  {willShip && (
                    <span className="ms-auto inline-flex items-center gap-1.5 rounded-full bg-warning-soft px-2.5 py-1 text-xs font-semibold text-warning">
                      <PackageCheck size={13} aria-hidden />
                      يتحول إلى «جاري الشحن» عند الحفظ
                    </span>
                  )}
                </div>

                <label className="block">
                  <span className="mb-1.5 flex items-center gap-2 text-[13px] font-semibold text-ink-soft">
                    <Truck size={15} className="text-violet" aria-hidden />
                    شركة النقل
                  </span>
                  <select
                    aria-label="شركة النقل"
                    disabled={save.isPending}
                    value={companyId ?? ""}
                    onChange={(event) => {
                      companyTouched.current = true;
                      setCompanyId(Number(event.target.value) || null);
                    }}
                    className="h-11 w-full rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:border-violet/45"
                  >
                    <option value="">— اختر —</option>
                    {companies.map((company) => (
                      <option key={company.id} value={company.id}>
                        {company.name}
                      </option>
                    ))}
                  </select>
                </label>

                {details.data && shippingSlots(details.data.items).length > 1 && (
                  <div>
                    <div
                      role="radiogroup"
                      aria-label="طريقة أرقام الوصولات"
                      className="grid grid-cols-2 gap-1 rounded-control bg-violet-soft p-1"
                    >
                      {(
                        [
                          { value: "order", label: "وصل واحد للطلب" },
                          { value: "pieces", label: "وصل لكل قطعة" },
                        ] as const
                      ).map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          role="radio"
                          aria-checked={mode === option.value}
                          disabled={save.isPending}
                          onClick={() => {
                            setMode(option.value);
                            setError(null);
                            setSubmitRequested(false);
                          }}
                          className={cn(
                            "h-10 rounded-control text-sm",
                            mode === option.value
                              ? "bg-white font-semibold text-violet-deep shadow-control"
                              : "text-ink-soft",
                          )}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                    {mode === "order" && (order?.shipping_barcodes?.length ?? 0) > 1 && (
                      <p className="mt-2 text-xs text-warning">
                        الحفظ بوصل واحد سيستبدل أرقام القطع السابقة؛ تبقى الأرقام القديمة بسجل الحركات.
                      </p>
                    )}
                  </div>
                )}

                <div>
                  <p className="mb-1.5 flex items-center justify-between text-[13px] font-semibold text-ink-soft">
                    <span className="flex items-center gap-2">
                      <ScanBarcode size={15} className="text-violet" aria-hidden />
                      {slots.length > 1 ? `وصل لكل قطعة (${slots.length})` : "رقم الوصل / البوليصة"}
                      <FeatureHelp
                        label="شرح أرقام الوصولات"
                        text="اكتب الرقم كما مطبوع بوصل شركة النقل، أو امسح باركوده. وصل واحد يكفي للطلب؛ اختر وصل لكل قطعة إذا شركة النقل تعطي أرقاماً منفصلة. الرقم محفوظ مع الطلب ويظهر بالبحث والطباعة والسجل."
                      />
                    </span>
                    <span className="ltr-isolate flex items-center gap-1 text-xs font-normal text-ink-faint">
                      {!ready && <Loader2 size={11} className="animate-spin" aria-hidden />}
                      {barcodes.filter((b) => b.trim()).length}/{slots.length}
                    </span>
                  </p>
                  <ul className="space-y-2">
                    {slots.map((slot, index) => {
                      const value = barcodes[index] ?? "";
                      const repeated =
                        value.trim() !== "" && barcodes.findIndex((b) => b.trim() === value.trim()) !== index;
                      return (
                        <li key={index}>
                          <label
                            className={cn(
                              "flex items-center gap-3 rounded-control bg-white px-3 py-2 ring-1 transition-colors focus-within:ring-2 focus-within:ring-violet/40",
                              repeated ? "ring-danger/50" : value.trim() ? "ring-success/35" : "ring-line/70",
                            )}
                          >
                            <span className="w-32 shrink-0 truncate text-xs text-ink-soft" title={slot.label}>
                              {slot.label}
                            </span>
                            <input
                              ref={(node) => {
                                inputs.current[index] = node;
                              }}
                              aria-label={
                                scan.receiptMode
                                  ? `رقم وصل شركة النقل ${index + 1}`
                                  : `باركود الشحن ${index + 1}`
                              }
                              maxLength={200}
                              disabled={save.isPending}
                              dir="ltr"
                              autoComplete="off"
                              spellCheck={false}
                              value={value}
                              placeholder="اكتب رقم الوصل أو امسح الباركود"
                              onChange={(event) => setBarcode(index, event.target.value)}
                              onKeyDown={onFieldKey(index)}
                              onFocus={(event) => event.target.select()}
                              className="ltr-isolate h-9 min-w-0 flex-1 bg-transparent font-mono text-[15px] tracking-wide text-ink outline-none placeholder:font-sans placeholder:text-sm placeholder:tracking-normal placeholder:text-ink-faint"
                            />
                            {value.trim() && !repeated && (
                              <CheckCircle2 size={16} className="shrink-0 text-success" aria-hidden />
                            )}
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </div>
            )}

            <footer className="border-t border-line/70 bg-white/70 px-5 py-3.5">
              {error && (
                <p
                  role="alert"
                  className="mb-2.5 rounded-control bg-danger-soft px-3.5 py-2 text-sm text-danger"
                >
                  {error}
                </p>
              )}
              <div className="flex items-center gap-2.5">
                {orderId !== null && (
                  <button
                    type="button"
                    onClick={() => onShowDetails(orderId)}
                    className="flex h-11 items-center gap-1.5 rounded-control px-3 text-sm text-ink-soft hover:bg-surface-sunken"
                  >
                    <Eye size={15} aria-hidden />
                    التفاصيل
                  </button>
                )}
                <p className="text-xs text-ink-faint">
                  {autoSave ? "Enter للانتقال والحفظ" : "Enter للانتقال"}
                </p>
                <button
                  ref={saveButton}
                  type="button"
                  disabled={!canSave}
                  onClick={submit}
                  className="ms-auto flex h-11 items-center gap-2 rounded-control bg-gradient-to-l from-violet to-violet-deep px-6 text-[15px] font-bold text-white shadow-float transition-opacity disabled:opacity-45"
                >
                  {save.isPending || submitRequested ? (
                    <Loader2 size={17} className="animate-spin" aria-hidden />
                  ) : (
                    <CheckCircle2 size={17} aria-hidden />
                  )}
                  {save.isPending ? "جارٍ الحفظ…" : scan.receiptMode ? "حفظ رقم الوصل" : "حفظ باركود الشحن"}
                </button>
              </div>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
