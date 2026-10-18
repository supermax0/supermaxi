import { AnimatePresence, motion } from "framer-motion";
import {
  Check,
  ChevronDown,
  FilePen,
  Minus,
  Percent,
  Plus,
  Printer,
  ScanBarcode,
  ShoppingCart,
  Trash2,
  X,
} from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import { productImageUrl } from "@/api/finora/products";
import type { PosBootstrap } from "@/api/finora/pos";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { Menu } from "@/components/Menu";
import { ProductThumb } from "@/components/ProductThumb";
import { cartTotals, useCart, type CartLine } from "@/features/pos/cart";
import { usePosPreferences } from "@/features/pos/posPreferences";
import { cn } from "@/utils/cn";
import { selectAfterFormatSwap } from "@/utils/selectOnFocus";
import { formatNumber } from "@/utils/format";
import { FeatureHelp } from "@/components/FeatureHelp";

interface CartPanelProps {
  bootstrap: PosBootstrap | undefined;
  serverUrl: string | null;
  busy: boolean;
  /** Changes after every successful checkout (drives the ✓ state of the button). */
  successToken: number;
  onCheckout(print: boolean): void;
  onEditInvoice(): void;
}

function Kbd({ children }: { children: string }) {
  return (
    <kbd aria-hidden className="ltr-isolate rounded-md bg-white/20 px-1.5 py-0.5 text-[11px] font-semibold">
      {children}
    </kbd>
  );
}

/** Edits the raw number while focused; shows 282,000 otherwise (no caret jumps while typing). */
function PriceInput({
  value,
  label,
  onCommit,
}: {
  value: number;
  label: string;
  onCommit(value: number): void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input
      aria-label={label}
      dir="ltr"
      inputMode="numeric"
      value={draft ?? formatNumber(value)}
      onFocus={(event) => {
        setDraft(String(value));
        selectAfterFormatSwap(event.target, String(value));
      }}
      onChange={(event) => {
        const digits = event.target.value.replace(/\D/g, "");
        setDraft(digits);
        onCommit(Number(digits) || 0);
      }}
      onBlur={() => setDraft(null)}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
      }}
      className="ltr-isolate h-9 w-[92px] rounded-[10px] border border-transparent bg-transparent text-center text-sm transition-colors hover:border-line focus:border-violet/45 focus:bg-white focus:outline-none"
    />
  );
}

const LineRow = memo(function LineRow({
  line,
  canEditPrice,
  showImage,
  serverUrl,
  flashAt,
  sources,
  busy,
}: {
  line: CartLine;
  canEditPrice: boolean;
  showImage: boolean;
  serverUrl: string | null;
  flashAt: number | null;
  sources: NonNullable<PosBootstrap["storage_sources"]>;
  busy: boolean;
}) {
  const setQty = useCart((s) => s.setQty);
  const setPrice = useCart((s) => s.setPrice);
  const remove = useCart((s) => s.remove);
  const setStorageSource = useCart((s) => s.setStorageSource);
  const row = useRef<HTMLTableRowElement>(null);
  const physicalQty = useCart((s) =>
    s.lines
      .filter((item) => item.productId === line.productId && item.color === line.color)
      .reduce((sum, item) => sum + item.qty, 0),
  );
  const short = line.available < physicalQty;

  // Highlight the line that was just added or incremented (scan / + button).
  useEffect(() => {
    const element = row.current;
    if (!flashAt || !element) return;
    if (typeof element.scrollIntoView === "function") {
      element.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    if (typeof element.animate === "function") {
      element.animate(
        [{ backgroundColor: "rgb(240 235 255 / 1)" }, { backgroundColor: "rgb(240 235 255 / 0)" }],
        { duration: 900, easing: "ease-out" },
      );
    }
  }, [flashAt]);

  return (
    <motion.tr
      ref={row}
      data-line={line.key}
      className="h-[58px] border-b border-line/60 last:border-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.12 } }}
      transition={{ duration: 0.18 }}
    >
      <td className="ps-4">
        <div className="flex items-center gap-3">
          {showImage && <ProductThumb src={productImageUrl(line.imageUrl, serverUrl)} size={40} />}
          <div className="min-w-0">
            <p className="truncate text-[13.5px] font-semibold text-ink">{line.name}</p>
            <span
              className={cn(
                "text-xs",
                line.saleMode === "exchange" ? "font-semibold text-violet" : "text-ink-faint",
              )}
            >
              {line.saleMode === "exchange" ? "استبدال" : "بيع"}
            </span>
            <p className={cn("truncate text-xs", short ? "text-warning" : "text-ink-faint")}>
              {short ? `المتوفر ${formatNumber(line.available)} — سيُقفل بانتظار المخزون` : line.detail}
            </p>
            {sources.length > 0 && (
              <div className="mt-1 flex items-center gap-2">
                <select
                  aria-label={`مصدر ${line.name}`}
                  disabled={busy}
                  value={line.storageSource?.key ?? "auto"}
                  onChange={(event) =>
                    setStorageSource(
                      line.key,
                      sources.find((source) => source.key === event.target.value),
                    )
                  }
                  className="h-8 min-w-0 max-w-full rounded-control border border-line bg-white px-2 text-xs text-ink-soft outline-none focus:border-violet"
                >
                  {sources.map((source) => (
                    <option key={source.key} value={source.key}>
                      {source.name}
                    </option>
                  ))}
                </select>
                <FeatureHelp
                  label={`شرح مصدر ${line.name}`}
                  text="اترك المصدر تلقائياً ليسحب من مواقع البيع والتخزين المتاحة. إذا حددت مخزناً ينحصر السحب فيه؛ التالف والرواجع للمراجعة لا تتاح للبيع."
                />
              </div>
            )}
          </div>
        </div>
      </td>
      <td className="text-center">
        <div className="inline-flex h-9 items-center overflow-hidden rounded-[10px] border border-line bg-white">
          <button
            type="button"
            aria-label={`إنقاص ${line.name}`}
            onClick={() => setQty(line.key, line.qty - 1)}
            className="grid h-full w-8 place-items-center text-ink-soft transition-colors hover:bg-surface-sunken hover:text-ink active:scale-90"
          >
            <Minus size={14} />
          </button>
          <input
            aria-label={`كمية ${line.name}`}
            dir="ltr"
            inputMode="numeric"
            value={line.qty}
            onFocus={(event) => event.target.select()}
            onChange={(event) => setQty(line.key, Number(event.target.value.replace(/\D/g, "")) || 0)}
            className="ltr-isolate h-full w-9 border-x border-line text-center text-sm font-semibold outline-none"
          />
          <button
            type="button"
            aria-label={`زيادة ${line.name}`}
            onClick={() => setQty(line.key, line.qty + 1)}
            className="grid h-full w-8 place-items-center text-ink-soft transition-colors hover:bg-surface-sunken hover:text-ink active:scale-90"
          >
            <Plus size={14} />
          </button>
        </div>
      </td>
      <td className="text-center">
        {canEditPrice ? (
          <PriceInput
            value={line.unitPrice}
            label={`سعر ${line.name}`}
            onCommit={(price) => setPrice(line.key, price)}
          />
        ) : (
          <span className="ltr-isolate text-sm">{formatNumber(line.unitPrice)}</span>
        )}
      </td>
      <td className="text-center">
        <span className="ltr-isolate text-sm font-bold">{formatNumber(line.unitPrice * line.qty)}</span>
      </td>
      <td className="pe-3 text-center">
        <button
          type="button"
          aria-label={`حذف ${line.name}`}
          onClick={() => remove(line.key)}
          className="grid h-8 w-8 place-items-center rounded-[9px] bg-danger-soft text-danger transition-colors hover:bg-danger hover:text-white active:scale-90"
        >
          <X size={15} />
        </button>
      </td>
    </motion.tr>
  );
});

export function CartPanel({
  bootstrap,
  serverUrl,
  busy,
  successToken,
  onCheckout,
  onEditInvoice,
}: CartPanelProps) {
  const lines = useCart((s) => s.lines);
  const discountMode = useCart((s) => s.discountMode);
  const discountValue = useCart((s) => s.discountValue);
  const editingOrderId = useCart((s) => s.editingOrderId);
  const lastAdded = useCart((s) => s.lastAdded);
  const setDiscount = useCart((s) => s.setDiscount);
  const clearLines = useCart((s) => s.clearLines);
  const reset = useCart((s) => s.reset);
  const showImages = usePosPreferences((s) => s.showImages);
  const autoPrint = usePosPreferences((s) => s.autoPrint);
  const defaultSaleType = usePosPreferences((s) => s.defaultSaleType);
  const totals = cartTotals(lines, discountMode, discountValue);
  const canPrint = bootstrap?.can_print ?? false;
  const printDefault = canPrint && autoPrint;
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!successToken) return;
    setDone(true);
    const timer = window.setTimeout(() => setDone(false), 1400);
    return () => window.clearTimeout(timer);
  }, [successToken]);

  const executeLabel = busy
    ? "جارٍ التنفيذ…"
    : editingOrderId
      ? "حفظ التعديل"
      : printDefault
        ? "تنفيذ و طباعة"
        : "تنفيذ";

  return (
    <section aria-label="سلة المبيعات" className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-3 px-5 py-3">
        <ShoppingCart size={22} className="text-violet-deep" aria-hidden />
        <h2 className="text-[17px] font-bold text-ink">
          {editingOrderId ? `تعديل الطلب #${editingOrderId}` : "سلة المبيعات"}
        </h2>
        <motion.span
          key={totals.items}
          initial={{ scale: 1.35 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 600, damping: 18 }}
          className="ltr-isolate grid h-7 min-w-7 place-items-center rounded-full bg-violet-soft px-2 text-sm font-semibold text-violet-deep"
        >
          {formatNumber(totals.items)}
        </motion.span>
        <button
          type="button"
          disabled={lines.length === 0}
          onClick={clearLines}
          className="ms-auto flex items-center gap-1.5 rounded-control bg-danger-soft/70 px-3 py-1.5 text-sm text-danger transition-colors hover:bg-danger-soft disabled:opacity-40"
        >
          تفريغ السلة
          <Trash2 size={15} aria-hidden />
        </button>
      </header>

      <div className="relative mx-4 min-h-0 flex-1 overflow-auto rounded-panel bg-white/75 ring-1 ring-line/60">
        <table className="w-full table-fixed">
          <thead className="sticky top-0 z-10 bg-[#f8f7fd]/95 text-[12.5px] font-semibold text-ink-soft">
            <tr className="h-11 border-b border-line">
              <th className="ps-4 text-start">المنتج</th>
              <th className="w-[124px]">الكمية</th>
              <th className="w-[110px]">السعر</th>
              <th className="w-[110px]">المجموع</th>
              <th className="w-12" aria-label="حذف" />
            </tr>
          </thead>
          <tbody>
            <AnimatePresence initial={false}>
              {lines.map((line) => (
                <LineRow
                  key={line.key}
                  line={line}
                  canEditPrice={bootstrap?.can_edit_price ?? false}
                  showImage={showImages}
                  serverUrl={serverUrl}
                  flashAt={lastAdded?.key === line.key ? lastAdded.at : null}
                  sources={bootstrap?.storage_sources ?? []}
                  busy={busy}
                />
              ))}
            </AnimatePresence>
          </tbody>
        </table>
        <AnimatePresence>
          {lines.length === 0 && (
            <motion.div
              className="flex flex-col items-center gap-2 py-12 text-center text-sm text-ink-faint"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1, transition: { delay: 0.1 } }}
              exit={{ opacity: 0, transition: { duration: 0.08 } }}
            >
              <span className="grid h-14 w-14 place-items-center rounded-full bg-surface-sunken">
                <ScanBarcode size={26} aria-hidden />
              </span>
              <p>امسح الباركود أو اضغط + على منتج لإضافته</p>
              <p className="text-xs">
                <kbd className="ltr-isolate rounded border border-line px-1">F2</kbd> بحث منتج ·{" "}
                <kbd className="ltr-isolate rounded border border-line px-1">F3</kbd> بحث زبون ·{" "}
                <kbd className="ltr-isolate rounded border border-line px-1">F9</kbd> تنفيذ
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="mx-4 mt-2.5 flex items-center gap-3 rounded-panel bg-white/75 px-4 py-2 ring-1 ring-line/60">
        <Percent size={18} className="text-maroon" aria-hidden />
        <span className="text-sm text-ink-soft">خصم على الفاتورة</span>
        <input
          aria-label="قيمة الخصم"
          dir="ltr"
          inputMode="numeric"
          value={discountValue || ""}
          placeholder="0"
          onChange={(event) => setDiscount(discountMode, Number(event.target.value.replace(/\D/g, "")) || 0)}
          className="ltr-isolate h-9 flex-1 rounded-[10px] border border-line bg-white px-3 text-sm outline-none transition-colors focus:border-violet/45"
        />
        <select
          aria-label="نوع الخصم"
          value={discountMode}
          onChange={(event) =>
            setDiscount(event.target.value === "percent" ? "percent" : "amount", discountValue)
          }
          className="h-9 rounded-[10px] border border-line bg-white px-2 text-sm outline-none"
        >
          <option value="amount">مبلغ ثابت</option>
          <option value="percent">نسبة %</option>
        </select>
      </div>

      <div className="mx-4 mt-2.5 grid grid-cols-2 gap-x-6 rounded-panel bg-white/75 px-5 py-2 text-sm ring-1 ring-line/60">
        <div className="flex justify-between text-ink-soft">
          <span>المجموع الفرعي</span>
          <span className="ltr-isolate font-semibold text-ink">
            <AnimatedNumber value={totals.subtotal} /> د.ع
          </span>
        </div>
        <div className="flex justify-between text-ink-soft">
          <span>الخصم</span>
          <span className="ltr-isolate font-semibold text-ink">
            <AnimatedNumber value={totals.discount} /> د.ع
          </span>
        </div>
      </div>
      <div className="mx-4 mt-2 flex items-center justify-between rounded-panel bg-gradient-to-l from-maroon-soft via-violet-soft/70 to-white px-5 py-2.5">
        <span className="text-base font-semibold text-ink">الإجمالي</span>
        <span className="ltr-isolate text-[26px] font-bold text-ink" data-testid="pos-total">
          <AnimatedNumber value={totals.total} /> <span className="text-sm font-medium">د.ع</span>
        </span>
      </div>

      <div className="flex gap-3 px-4 pb-4 pt-3">
        <div
          className={cn(
            "flex h-[52px] flex-[2] overflow-hidden rounded-control text-white shadow-float transition-colors duration-300",
            done ? "bg-success" : "bg-gradient-to-l from-maroon to-[#9b2c55]",
          )}
        >
          <button
            type="button"
            disabled={busy || lines.length === 0}
            aria-label={done ? "تم التنفيذ" : executeLabel}
            title="F9 / Ctrl+Enter"
            onClick={() => onCheckout(printDefault)}
            className="flex flex-1 items-center justify-center gap-2.5 text-[16px] font-bold transition-opacity active:opacity-80 disabled:opacity-50"
          >
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={done ? "done" : busy ? "busy" : "idle"}
                className="flex items-center gap-2.5"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.16 }}
              >
                {done ? (
                  <>
                    <Check size={20} aria-hidden /> تم التنفيذ
                  </>
                ) : (
                  <>
                    {printDefault && !busy ? <Printer size={20} aria-hidden /> : null}
                    {executeLabel}
                    {!busy && <Kbd>F9</Kbd>}
                  </>
                )}
              </motion.span>
            </AnimatePresence>
          </button>
          {canPrint && (
            <Menu
              label="خيارات التنفيذ"
              items={[
                {
                  id: "print",
                  label: "تنفيذ و طباعة",
                  icon: Printer,
                  disabled: lines.length === 0,
                  onSelect: () => onCheckout(true),
                },
                {
                  id: "plain",
                  label: "تنفيذ بدون طباعة",
                  icon: ShoppingCart,
                  disabled: lines.length === 0,
                  onSelect: () => onCheckout(false),
                },
              ]}
              trigger={(props) => (
                <button
                  {...props}
                  type="button"
                  aria-label="خيارات التنفيذ"
                  disabled={busy}
                  className="grid w-12 place-items-center border-s border-white/20 transition-colors hover:bg-white/10"
                >
                  <ChevronDown size={18} />
                </button>
              )}
            />
          )}
        </div>
        <button
          type="button"
          onClick={onEditInvoice}
          className="flex h-[52px] flex-1 items-center justify-center gap-2 rounded-control bg-azure-soft/80 text-[15px] font-semibold text-azure ring-1 ring-azure/15 transition-colors hover:bg-azure-soft"
        >
          <FilePen size={18} aria-hidden />
          تعديل فاتورة
        </button>
        <button
          type="button"
          onClick={() => reset(defaultSaleType)}
          className="flex h-[52px] w-24 flex-col items-center justify-center rounded-control bg-white text-sm font-semibold text-danger ring-1 ring-line transition-colors hover:bg-danger-soft"
        >
          <X size={20} aria-hidden />
          إلغاء
        </button>
      </div>
    </section>
  );
}
