import { ProductThumb } from "@/components/ProductThumb";
import { productImageUrl } from "@/api/finora/products";
import { FeatureHelp } from "@/components/FeatureHelp";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  Building2,
  Check,
  CheckCircle2,
  Loader2,
  Minus,
  PackagePlus,
  Plus,
  Save,
  ScanBarcode,
  Search,
  Truck,
  UserPlus,
  X,
} from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { PurchaseProduct } from "@/api/finora/purchases";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { IconButton } from "@/components/IconButton";
import { Popover } from "@/components/Popover";
import { bankAccountsFor } from "@/features/pos/bankAccounts";
import {
  composerTotals,
  lineTotal,
  toNewPurchase,
  useComposer,
  validateComposer,
  type ComposerLine,
  type ComposerSupplier,
} from "@/features/purchases/composer";
import { useBarcodeScanner } from "@/hooks/useBarcodeScanner";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { canMutate } from "@/stores/connection";
import { useCan, useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { MoneyInput } from "@/components/MoneyInput";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { SaleTypePicker } from "../pos/SaleTypePicker";

const PAY_HINTS = {
  cash: "يُسجَّل الدفع كاملاً من صندوق الفرع",
  credit: "يبقى المبلغ ديناً للمورد (يمكن تسجيل دفعة مقدمة)",
  bank: "يُسجَّل الدفع كاملاً من الحساب البنكي",
} as const;

const fieldBox =
  "flex h-11 items-center gap-2.5 rounded-control border border-line bg-white/90 px-3.5 transition-[border-color,box-shadow] focus-within:border-violet/45 focus-within:ring-4 focus-within:ring-violet/10";
const plainInput =
  "h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint";

function Step({ index, label, done }: { index: number; label: string; done: boolean }) {
  return (
    <span
      className={cn(
        "flex items-center gap-2 text-[13px] font-medium",
        done ? "text-success" : "text-ink-soft",
      )}
    >
      <span
        className={cn(
          "grid h-6 w-6 place-items-center rounded-full text-xs font-bold transition-colors duration-300",
          done ? "bg-success text-white" : "bg-surface-sunken text-ink-soft",
        )}
      >
        {done ? <Check size={13} strokeWidth={3} /> : index}
      </span>
      {label}
    </span>
  );
}

function SupplierPicker({ suppliers }: { suppliers: ComposerSupplier[] }) {
  const supplier = useComposer((s) => s.supplier);
  const patch = useComposer((s) => s.patch);
  const canCreate = useCan("can_manage_suppliers");
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [creating, setCreating] = useState(false);
  const [phone, setPhone] = useState("");
  const anchor = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const matches = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return (needle ? suppliers.filter((s) => s.name.toLowerCase().includes(needle)) : suppliers).slice(0, 40);
  }, [suppliers, text]);

  const create = useMutation({
    mutationFn: () => finora.purchases.quickCreateSupplier({ name: text, phone }),
    onSuccess: (created) => {
      patch({ supplier: created });
      setOpen(false);
      setCreating(false);
      setText("");
      setPhone("");
      toast.success(`تمت إضافة المورد ${created.name}`);
      void queryClient.invalidateQueries({ queryKey: ["purchases"] });
    },
    onError: (error) => toast.error(toFinoraError(error).message),
  });

  return (
    <div ref={anchor} className="relative">
      {supplier ? (
        <div className="flex items-center gap-3 rounded-control bg-gradient-to-l from-violet-soft to-white px-4 py-3 ring-1 ring-violet/15">
          <span className="grid h-10 w-10 place-items-center rounded-full bg-white text-violet-deep shadow-control">
            <Building2 size={18} aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-xs text-ink-faint">المورد</p>
            <p className="truncate text-[15px] font-bold text-ink">{supplier.name}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              patch({ supplier: null });
              setOpen(true);
            }}
            className="rounded-full px-2.5 py-1 text-xs font-semibold text-violet-deep hover:bg-white"
          >
            تغيير
          </button>
        </div>
      ) : (
        <label className={fieldBox}>
          <Building2 size={17} className="text-ink-faint" aria-hidden />
          <input
            aria-label="المورد"
            value={text}
            placeholder="ابحث عن المورد…"
            onFocus={() => setOpen(true)}
            onChange={(event) => {
              setText(event.target.value);
              setOpen(true);
              setCreating(false);
            }}
            className={plainInput}
          />
        </label>
      )}
      <Popover
        open={open && !supplier}
        onClose={() => setOpen(false)}
        anchor={anchor}
        label="الموردون"
        align="stretch"
      >
        {creating ? (
          <div className="space-y-2.5 p-2">
            <p className="text-sm font-semibold text-ink">مورد جديد</p>
            <label className={fieldBox}>
              <input
                aria-label="اسم المورد الجديد"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="اسم المورد"
                className={plainInput}
              />
            </label>
            <label className={fieldBox}>
              <input
                aria-label="هاتف المورد"
                dir="ltr"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="الهاتف (اختياري)"
                className={cn(plainInput, "text-end")}
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="h-9 rounded-control px-3 text-sm text-ink-soft hover:bg-surface-sunken"
              >
                رجوع
              </button>
              <button
                type="button"
                disabled={!text.trim() || create.isPending}
                onClick={() => create.mutate()}
                className="h-9 rounded-control bg-gradient-to-l from-violet to-violet-deep px-4 text-sm font-semibold text-white disabled:opacity-50"
              >
                {create.isPending ? "جارٍ الحفظ…" : "حفظ المورد"}
              </button>
            </div>
          </div>
        ) : (
          <>
            <ul role="listbox" aria-label="الموردون" className="max-h-[260px] overflow-y-auto">
              {matches.length === 0 && (
                <li className="px-3 py-3 text-sm text-ink-faint">لا يوجد مورد بهذا الاسم</li>
              )}
              {matches.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={false}
                    onClick={() => {
                      patch({ supplier: item });
                      setOpen(false);
                      setText("");
                    }}
                    className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-start text-sm text-ink transition-colors hover:bg-violet-soft"
                  >
                    <Building2 size={15} className="text-ink-faint" aria-hidden />
                    {item.name}
                  </button>
                </li>
              ))}
            </ul>
            {canCreate && (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="mt-1 flex w-full items-center gap-2 rounded-[10px] border-t border-line px-3 py-2.5 text-sm font-semibold text-azure hover:bg-azure-soft"
              >
                <UserPlus size={16} aria-hidden />
                {text.trim() ? `إضافة «${text.trim()}» كمورد جديد` : "مورد جديد"}
              </button>
            )}
          </>
        )}
      </Popover>
    </div>
  );
}

function ProductSearch({ active }: { active: boolean }) {
  const addProduct = useComposer((s) => s.addProduct);
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState(0);
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const q = useDebouncedValue(text.trim(), 200);
  const results = useQuery({
    queryKey: ["purchases", "product-search", q],
    queryFn: () => finora.purchases.searchProducts(q),
    enabled: q.length >= 1,
    staleTime: 30_000,
    // keep the list mounted while the next keystroke's results load (no flicker, no lost click)
    placeholderData: keepPreviousData,
  });

  const add = useCallback(
    (product: PurchaseProduct) => {
      addProduct(product);
      setText("");
      setOpen(false);
      setCursor(0);
      input.current?.focus();
    },
    [addProduct],
  );

  const scan = useCallback(
    async (code: string) => {
      try {
        const found = await finora.purchases.searchProducts(code);
        const [first] = found;
        if (first && (found.length === 1 || first.barcode === code)) add(first);
        else {
          setText(code);
          setOpen(true);
        }
      } catch (error) {
        toast.error(toFinoraError(error).message);
      }
    },
    [add],
  );
  useBarcodeScanner(
    useCallback((code: string) => void scan(code), [scan]),
    active,
  );
  useEffect(() => {
    if (active) requestAnimationFrame(() => input.current?.focus());
  }, [active]);

  const rows = results.data ?? [];
  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(c + 1, Math.max(rows.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const row = rows[cursor];
      if (row && q === text.trim()) add(row);
      else if (text.trim()) void scan(text.trim());
    }
  };

  return (
    <div ref={anchor} className="relative">
      <label className={cn(fieldBox, "h-12 bg-white")}>
        {results.isFetching ? (
          <Loader2 size={18} className="animate-spin text-violet" aria-hidden />
        ) : (
          <Search size={18} className="text-ink-faint" aria-hidden />
        )}
        <input
          ref={input}
          aria-label="إضافة منتج"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
            setCursor(0);
          }}
          onFocus={() => text && setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="ابحث عن منتج بالاسم أو SKU أو امسح الباركود…"
          className={cn(plainInput, "text-[15px]")}
        />
        <ScanBarcode size={19} className="text-ink-soft" aria-label="يدعم قارئ الباركود" />
      </label>
      <Popover
        open={open && q.length >= 1}
        onClose={() => setOpen(false)}
        anchor={anchor}
        label="نتائج المنتجات"
        align="stretch"
      >
        {results.isLoading && <p className="px-3 py-3 text-sm text-ink-faint">جارٍ البحث…</p>}
        {!results.isLoading && rows.length === 0 && (
          <p className="px-3 py-3 text-sm text-ink-faint">لا يوجد منتج مطابق</p>
        )}
        <ul role="listbox" aria-label="نتائج المنتجات" className="max-h-[300px] overflow-y-auto">
          {rows.map((product, index) => (
            <li key={product.id}>
              <button
                type="button"
                role="option"
                aria-selected={index === cursor}
                onMouseEnter={() => setCursor(index)}
                onClick={() => add(product)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-start transition-colors",
                  index === cursor ? "bg-violet-soft" : "hover:bg-surface-sunken",
                )}
              >
                <PackagePlus size={17} className="shrink-0 text-violet" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-ink">{product.name}</span>
                  <span className="ltr-isolate block truncate text-xs text-ink-faint">
                    {product.sku || product.barcode}
                  </span>
                </span>
                <span className="text-end text-xs text-ink-soft">
                  <span className="block">
                    آخر شراء{" "}
                    <span className="ltr-isolate font-semibold text-ink">
                      {formatNumber(product.buy_price)}
                    </span>
                  </span>
                  <span className="block">
                    المخزون <span className="ltr-isolate">{formatNumber(product.quantity)}</span>
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Popover>
    </div>
  );
}

const LineRow = memo(function LineRow({
  line,
  index,
  flashAt,
}: {
  line: ComposerLine;
  index: number;
  flashAt: number | null;
}) {
  const updateLine = useComposer((s) => s.updateLine);
  const removeLine = useComposer((s) => s.removeLine);
  const row = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    const element = row.current;
    if (!flashAt || !element) return;
    if (typeof element.scrollIntoView === "function")
      element.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (typeof element.animate === "function") {
      element.animate(
        [{ backgroundColor: "rgb(240 235 255 / 1)" }, { backgroundColor: "rgb(240 235 255 / 0)" }],
        {
          duration: 900,
          easing: "ease-out",
        },
      );
    }
  }, [flashAt]);
  const badDiscount = line.discount > line.unitCost;
  const optionImage = line.optionDetails?.find((option) => option.name === line.color)?.image_url;
  return (
    <motion.tr
      ref={row}
      data-line={line.key}
      className="h-[62px] border-b border-line/60 last:border-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.12 } }}
      transition={{ duration: 0.18 }}
    >
      <td className="ps-4 text-xs text-ink-faint">
        <span className="ltr-isolate">{index + 1}</span>
      </td>
      <td className="px-2">
        <div className="flex items-center gap-2">
          {optionImage && <ProductThumb src={productImageUrl(optionImage, null)} size={36} />}
          <p className="truncate text-[13.5px] font-semibold text-ink">{line.name}</p>
        </div>
        <p className="flex items-center gap-2 text-xs text-ink-faint">
          <span className="ltr-isolate truncate">{line.sku}</span>
          <span>· المخزون {formatNumber(line.stock)}</span>
        </p>
      </td>
      <td className="px-2">
        {line.colors.length > 0 ? (
          <div className="flex items-center gap-1">
            <FeatureHelp text="اختر الحجم أو المقاس أو تركيبة اللون والمقاس المستلمة. الكمية تضاف لمخزون هذا الخيار فقط، وسعر الشراء الخاص به يظهر تلقائياً ويمكنك تعديله حسب الفاتورة." />
            <select
              aria-label={`خيار ${line.name}`}
              value={line.color}
              onChange={(event) => updateLine(line.key, { color: event.target.value })}
              className={cn(
                "h-9 w-full rounded-[10px] border bg-white px-2 text-sm",
                line.color ? "border-line" : "border-warning text-warning",
              )}
            >
              <option value="">اختر الخيار</option>
              {line.colors.map((color) => (
                <option key={color} value={color}>
                  {color}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <span className="text-xs text-ink-faint">—</span>
        )}
      </td>
      <td className="text-center">
        <div className="inline-flex h-9 items-center overflow-hidden rounded-[10px] border border-line bg-white">
          <button
            type="button"
            aria-label={`إنقاص ${line.name}`}
            onClick={() => updateLine(line.key, { qty: Math.max(1, line.qty - 1) })}
            className="grid h-full w-8 place-items-center text-ink-soft hover:bg-surface-sunken active:scale-90"
          >
            <Minus size={14} />
          </button>
          <input
            aria-label={`كمية ${line.name}`}
            dir="ltr"
            inputMode="numeric"
            value={line.qty}
            onFocus={(event) => event.target.select()}
            onChange={(event) =>
              updateLine(line.key, { qty: Number(event.target.value.replace(/\D/g, "")) || 0 })
            }
            className="ltr-isolate h-full w-11 border-x border-line text-center text-sm font-semibold outline-none"
          />
          <button
            type="button"
            aria-label={`زيادة ${line.name}`}
            onClick={() => updateLine(line.key, { qty: line.qty + 1 })}
            className="grid h-full w-8 place-items-center text-ink-soft hover:bg-surface-sunken active:scale-90"
          >
            <Plus size={14} />
          </button>
        </div>
      </td>
      <td className="px-2 text-center">
        <MoneyInput
          label={`سعر شراء ${line.name}`}
          value={line.unitCost}
          onChange={(unitCost) => updateLine(line.key, { unitCost })}
          className="w-[110px]"
        />
      </td>
      <td className="px-2 text-center">
        <MoneyInput
          label={`خصم ${line.name}`}
          value={line.discount}
          onChange={(discount) => updateLine(line.key, { discount })}
          className={cn("w-[92px]", badDiscount && "border-danger text-danger")}
        />
      </td>
      <td className="text-center">
        <span className="ltr-isolate text-sm font-bold text-ink">{formatNumber(lineTotal(line))}</span>
      </td>
      <td className="pe-3 text-center">
        <button
          type="button"
          aria-label={`حذف ${line.name}`}
          onClick={() => removeLine(line.key)}
          className="grid h-8 w-8 place-items-center rounded-[9px] bg-danger-soft text-danger transition-colors hover:bg-danger hover:text-white active:scale-90"
        >
          <X size={15} />
        </button>
      </td>
    </motion.tr>
  );
});

export function PurchaseComposer({ suppliers, active }: { suppliers: ComposerSupplier[]; active: boolean }) {
  const state = useComposer();
  const { open, lines, mode, discount, shippingExtra, downPayment, supplier, lastAdded } = state;
  const queryClient = useQueryClient();
  const branchId = useSession((s) => s.session?.branch?.id ?? null);
  const canPayAccounts = useCan("pay_orders");
  const totals = composerTotals(state);
  const [error, setError] = useState<string | null>(null);

  const accounts = useQuery({
    queryKey: ["pos", "accounts"],
    queryFn: () => finora.pos.paymentAccounts(),
    enabled: open && mode === "bank" && canPayAccounts,
    staleTime: 5 * 60_000,
  });
  const banks = useMemo(() => bankAccountsFor(accounts.data ?? [], branchId), [accounts.data, branchId]);
  useEffect(() => {
    if (mode !== "bank" || banks.length === 0) return;
    if (state.bankAccountId && banks.some((b) => b.id === state.bankAccountId)) return;
    if (banks.length === 1) state.patch({ bankAccountId: banks[0]?.id ?? null });
  }, [mode, banks, state]);

  const save = useMutation({
    mutationFn: (confirm: boolean) => {
      if (!canMutate()) throw new Error("لا يمكن الحفظ بدون اتصال بـ FINORA.");
      return finora.purchases.create(toNewPurchase(useComposer.getState(), confirm));
    },
    onSuccess: (created, confirm) => {
      toast.success(
        confirm
          ? `تم حفظ فاتورة الشراء ${created.invoice_no} وإضافة الكميات للمخزون`
          : `تم حفظ فاتورة الشراء ${created.invoice_no} كمسودة`,
      );
      useComposer.getState().reset();
      useComposer.getState().setOpen(false);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["purchases"] });
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      void queryClient.invalidateQueries({ queryKey: ["pos", "products"] });
    },
    onError: (failure) => {
      const message =
        failure instanceof Error && !("kind" in failure) ? failure.message : toFinoraError(failure).message;
      setError(message);
      toast.error(message);
    },
  });

  const submit = useCallback(
    (confirm: boolean) => {
      if (save.isPending) return;
      const problem = validateComposer(useComposer.getState());
      if (problem) {
        setError(problem);
        return;
      }
      if (mode === "bank" && canPayAccounts && banks.length > 1 && !useComposer.getState().bankAccountId) {
        setError("اختر الحساب البنكي.");
        return;
      }
      setError(null);
      save.mutate(confirm);
    },
    [save, mode, canPayAccounts, banks.length],
  );

  // Esc closes (the draft stays), Ctrl+Enter saves and confirms receipt.
  useEffect(() => {
    if (!open || !active) return;
    const onKey = (event: KeyboardEvent) => {
      if (document.querySelector('[data-popover], [aria-modal="true"]')) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        useComposer.getState().setOpen(false);
      } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submit(true);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, active, submit]);

  return (
    <AnimatePresence>
      {open && (
        <motion.section
          role="dialog"
          aria-label="فاتورة شراء جديدة"
          className="glass-solid absolute inset-0 z-40 flex flex-col overflow-hidden rounded-panel bg-[#fbfaff]"
          initial={{ opacity: 0, y: 18, scale: 0.99 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.99, transition: { duration: 0.16 } }}
          transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
          style={{ willChange: "transform, opacity" }}
        >
          <header className="flex items-center gap-4 border-b border-line/70 px-6 py-3.5">
            <span className="grid h-10 w-10 place-items-center rounded-control bg-azure-soft text-azure">
              <Truck size={20} aria-hidden />
            </span>
            <div>
              <h2 className="text-[17px] font-bold text-ink">فاتورة شراء جديدة</h2>
              <p className="text-xs text-ink-faint">يُحفظ ما تكتبه تلقائياً حتى تنتهي — Esc للإغلاق</p>
            </div>
            <div className="ms-auto flex items-center gap-5">
              <Step index={1} label="المورد" done={supplier !== null} />
              <span className="h-px w-6 bg-line" aria-hidden />
              <Step
                index={2}
                label={`المنتجات${lines.length ? ` (${lines.length})` : ""}`}
                done={lines.length > 0}
              />
              <span className="h-px w-6 bg-line" aria-hidden />
              <Step index={3} label="الدفع والحفظ" done={false} />
            </div>
            <IconButton label="إغلاق فاتورة الشراء" size="sm" onClick={() => state.setOpen(false)}>
              <X size={17} />
            </IconButton>
          </header>

          <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)] gap-4 p-4">
            <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto">
              <SupplierPicker suppliers={suppliers} />
              <label className="block">
                <span className="mb-1.5 block text-[12.5px] font-medium text-ink-soft">
                  رقم فاتورة المورد
                </span>
                <span className={fieldBox}>
                  <input
                    aria-label="رقم فاتورة المورد"
                    dir="ltr"
                    value={state.supplierInvoiceNo}
                    onChange={(e) => state.patch({ supplierInvoiceNo: e.target.value })}
                    placeholder="اختياري"
                    className={cn(plainInput, "text-end")}
                  />
                </span>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[12.5px] font-medium text-ink-soft">تاريخ الشراء</span>
                <span className={fieldBox}>
                  <input
                    aria-label="تاريخ الشراء"
                    type="date"
                    dir="ltr"
                    value={state.date}
                    onChange={(e) => state.patch({ date: e.target.value })}
                    className={plainInput}
                  />
                </span>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[12.5px] font-medium text-ink-soft">ملاحظات</span>
                <textarea
                  aria-label="ملاحظات"
                  rows={4}
                  value={state.notes}
                  onChange={(e) => state.patch({ notes: e.target.value })}
                  placeholder="مثال: شاشات متنوعة — تسليم الأسبوع القادم"
                  className="w-full resize-none rounded-control border border-line bg-white/90 px-3.5 py-2.5 text-sm leading-6 outline-none focus:border-violet/45 focus:ring-4 focus:ring-violet/10"
                />
              </label>
              <button
                type="button"
                disabled={lines.length === 0 && !supplier}
                onClick={() => state.reset()}
                className="mt-auto h-9 rounded-control text-sm text-ink-soft hover:bg-surface-sunken disabled:opacity-40"
              >
                تفريغ الفاتورة
              </button>
            </aside>

            <div className="flex min-h-0 flex-col gap-3">
              <ProductSearch active={open && active} />
              <div className="relative min-h-0 flex-1 overflow-auto rounded-panel bg-white/80 ring-1 ring-line/60">
                <table className="w-full table-fixed">
                  <thead className="sticky top-0 z-10 bg-[#f8f7fd]/95 text-[12.5px] font-semibold text-ink-soft">
                    <tr className="h-11 border-b border-line">
                      <th className="w-10 ps-4 text-start">#</th>
                      <th className="px-2 text-start">المنتج</th>
                      <th className="w-[130px] px-2 text-start">اللون</th>
                      <th className="w-[132px]">الكمية</th>
                      <th className="w-[130px]">سعر الشراء</th>
                      <th className="w-[108px]">خصم الوحدة</th>
                      <th className="w-[120px]">المجموع</th>
                      <th className="w-12" aria-label="حذف" />
                    </tr>
                  </thead>
                  <tbody>
                    <AnimatePresence initial={false}>
                      {lines.map((line, index) => (
                        <LineRow
                          key={line.key}
                          line={line}
                          index={index}
                          flashAt={lastAdded?.key === line.key ? lastAdded.at : null}
                        />
                      ))}
                    </AnimatePresence>
                  </tbody>
                </table>
                {lines.length === 0 && (
                  <div className="flex flex-col items-center gap-2 py-14 text-center text-sm text-ink-faint">
                    <span className="grid h-16 w-16 place-items-center rounded-full bg-azure-soft text-azure">
                      <PackagePlus size={28} aria-hidden />
                    </span>
                    <p className="text-base font-semibold text-ink">أضف المنتجات المشتراة</p>
                    <p>ابحث بالاسم أو امسح الباركود — سعر الشراء الأخير يُعبّأ تلقائياً ويمكنك تعديله.</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          <footer className="flex flex-wrap items-center gap-3 border-t border-line/70 bg-white/60 px-6 py-3.5">
            <SaleTypePicker
              label="طريقة الدفع"
              hints={PAY_HINTS}
              value={mode}
              onChange={(next) => state.patch({ mode: next })}
              canPay
              bankAccounts={banks}
              bankAccountId={state.bankAccountId}
              onBankAccount={(id) => state.patch({ bankAccountId: id })}
              loadingAccounts={accounts.isLoading}
            />
            {mode === "credit" && (
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                دفعة مقدمة
                <MoneyInput
                  label="دفعة مقدمة"
                  value={downPayment}
                  onChange={(v) => state.patch({ downPayment: v })}
                  className="w-[120px]"
                  placeholder="لا يوجد"
                />
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              خصم الفاتورة
              <MoneyInput
                label="خصم الفاتورة"
                value={discount}
                onChange={(v) => state.patch({ discount: v })}
                className="w-[110px]"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              شحن ومصاريف
              <MoneyInput
                label="شحن ومصاريف"
                value={shippingExtra}
                onChange={(v) => state.patch({ shippingExtra: v })}
                className="w-[110px]"
              />
            </label>

            <div className="ms-auto flex items-center gap-4">
              <div className="text-end">
                <p className="text-xs text-ink-faint">
                  <span className="ltr-isolate">{formatNumber(totals.units)}</span> قطعة · المجموع{" "}
                  <span className="ltr-isolate">{formatNumber(totals.subtotal)}</span>
                </p>
                <p
                  className="ltr-isolate text-[24px] font-bold leading-tight text-ink"
                  data-testid="purchase-total"
                >
                  <AnimatedNumber value={totals.grand} /> <span className="text-sm font-medium">د.ع</span>
                </p>
              </div>
              <button
                type="button"
                disabled={save.isPending}
                onClick={() => submit(false)}
                className="flex h-12 items-center gap-2 rounded-control bg-white px-4 text-sm font-semibold text-ink ring-1 ring-line transition-colors hover:bg-surface-sunken disabled:opacity-50"
              >
                <Save size={17} aria-hidden />
                حفظ كمسودة
              </button>
              <button
                type="button"
                disabled={save.isPending}
                onClick={() => submit(true)}
                title="Ctrl+Enter"
                className="flex h-12 items-center gap-2 rounded-control bg-gradient-to-l from-azure to-violet-deep px-5 text-[15px] font-bold text-white shadow-float transition-opacity hover:opacity-95 disabled:opacity-60"
              >
                {save.isPending ? (
                  <Loader2 size={18} className="animate-spin" aria-hidden />
                ) : (
                  <CheckCircle2 size={18} aria-hidden />
                )}
                {save.isPending ? "جارٍ الحفظ…" : "حفظ وتأكيد الاستلام"}
              </button>
            </div>
            <AnimatePresence>
              {error && (
                <motion.p
                  role="alert"
                  className="basis-full rounded-control bg-danger-soft px-4 py-2 text-sm text-danger"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  {error}
                </motion.p>
              )}
            </AnimatePresence>
          </footer>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
