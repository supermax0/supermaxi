import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  ExternalLink,
  ImagePlus,
  Loader2,
  Minus,
  PackagePlus,
  Palette,
  Plus,
  RefreshCw,
  Tag,
  TrendingUp,
  Wand2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import { MAX_UPLOAD_BYTES, MAX_TOTAL_UPLOAD_BYTES } from "@shared/ipc";
import { finora, toFinoraError } from "@/api/finora";
import {
  productImageUrl,
  type ImageUpload,
  type ColorImageChange,
  type ProductDetails,
  type ProductFields,
} from "@/api/finora/products";
import { ConfirmDialog } from "@/components/Dialog";
import { IconButton } from "@/components/IconButton";
import { generateStoreBarcode } from "@/features/products/barcode";
import { useBarcodeScanner } from "@/hooks/useBarcodeScanner";
import { canMutate } from "@/stores/connection";
import { useCan } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { selectAfterFormatSwap } from "@/utils/selectOnFocus";
import { formatNumber } from "@/utils/format";
import { ProductOptions, type OptionsDraft } from "./ProductOptions";

export type EditorTarget = { kind: "create" } | { kind: "edit"; id: number };

interface FormState {
  name: string;
  sku: string;
  barcode: string;
  buyPrice: number;
  salePrice: number;
  exchangePrice: number;
  posVisible: boolean;
  storeVisible: boolean;
  lowStock: number;
  category: string;
  brand: string;
  unit: string;
  description: string;
  active: boolean;
  openingStock: number;
}

const EMPTY: FormState = {
  name: "",
  sku: "",
  barcode: "",
  buyPrice: 0,
  salePrice: 0,
  exchangePrice: 0,
  posVisible: true,
  storeVisible: true,
  lowStock: 5,
  category: "",
  brand: "",
  unit: "",
  description: "",
  active: true,
  openingStock: 0,
};

function fromDetails(p: ProductDetails): FormState {
  return {
    name: p.name,
    sku: p.sku,
    barcode: p.barcode,
    buyPrice: p.buy_price,
    salePrice: p.sale_price,
    exchangePrice: p.exchange_sale_price ?? 0,
    posVisible: p.pos_visible,
    storeVisible: p.store_visible,
    lowStock: p.low_stock_threshold,
    category: p.category,
    brand: p.brand,
    unit: p.unit,
    description: p.description,
    active: p.active,
    openingStock: 0,
  };
}

/** Only fields that changed are sent — FINORA leaves every other field as it is. */
export function changedFields(before: FormState, after: FormState): ProductFields {
  const out: ProductFields = {};
  if (after.name !== before.name) out.name = after.name.trim();
  if (after.sku !== before.sku) out.sku = after.sku.trim();
  if (after.barcode !== before.barcode) out.barcode = after.barcode.trim();
  if (after.buyPrice !== before.buyPrice) out.buy_price = after.buyPrice;
  if (after.salePrice !== before.salePrice) out.sale_price = after.salePrice;
  if (after.exchangePrice !== before.exchangePrice) out.exchange_sale_price = after.exchangePrice;
  if (after.posVisible !== before.posVisible) out.pos_visible = after.posVisible;
  if (after.storeVisible !== before.storeVisible) out.store_visible = after.storeVisible;
  if (after.lowStock !== before.lowStock) out.low_stock_threshold = after.lowStock;
  if (after.category !== before.category) out.category = after.category.trim();
  if (after.brand !== before.brand) out.brand = after.brand.trim();
  if (after.unit !== before.unit) out.unit = after.unit.trim();
  if (after.description !== before.description) out.description = after.description.trim();
  if (after.active !== before.active) out.active = after.active;
  return out;
}

const inputBox =
  "h-11 w-full rounded-control border border-line bg-white/95 px-3.5 text-sm text-ink outline-none transition-[border-color,box-shadow] placeholder:text-ink-faint focus:border-violet/45 focus:ring-4 focus:ring-violet/10 disabled:bg-surface-sunken disabled:text-ink-soft";

function Section({
  title,
  icon: Icon,
  children,
  aside,
}: {
  title: string;
  icon: typeof Tag;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="rounded-panel bg-white/85 p-4 ring-1 ring-line/60">
      <h3 className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-ink-soft">
        <Icon size={16} aria-hidden />
        {title}
        {aside && <span className="ms-auto">{aside}</span>}
      </h3>
      {children}
    </section>
  );
}

function Labeled({
  label,
  required,
  children,
  hint,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
  hint?: ReactNode;
}) {
  // Inputs carry their own aria-label; hints (e.g. the "توليد" button) stay outside any <label>.
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1 text-[12.5px] font-medium text-ink-soft">
        <span>{label}</span>
        {required && <span className="text-danger">*</span>}
        {hint && <span className="ms-auto text-[11.5px] font-normal">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function MoneyField({
  value,
  onChange,
  label,
  disabled,
}: {
  value: number;
  onChange(v: number): void;
  label: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <div className="relative">
      <input
        aria-label={label}
        dir="ltr"
        inputMode="numeric"
        disabled={disabled}
        value={draft ?? (value ? formatNumber(value) : "")}
        placeholder="0"
        onFocus={(event) => {
          const raw = value ? String(value) : "";
          setDraft(raw);
          selectAfterFormatSwap(event.target, raw);
        }}
        onChange={(event) => {
          const digits = event.target.value.replace(/\D/g, "");
          setDraft(digits);
          onChange(Number(digits) || 0);
        }}
        onBlur={() => setDraft(null)}
        className={cn(inputBox, "ltr-isolate pe-12 text-end font-semibold")}
      />
      <span className="pointer-events-none absolute inset-y-0 end-3.5 grid place-items-center text-xs text-ink-faint">
        د.ع
      </span>
    </div>
  );
}

const STOCK_REASONS = ["جرد", "تلف", "خطأ إدخال", "مرتجع للمورد"] as const;

function StockAdjuster({ product, onDone }: { product: ProductDetails; onDone(): void }) {
  const [colorName, setColorName] = useState(product.colors[0]?.name ?? "");
  const [direction, setDirection] = useState<1 | -1>(1);
  const [amount, setAmount] = useState(1);
  const [reason, setReason] = useState<string>("جرد");
  const [confirming, setConfirming] = useState(false);
  const adjust = useMutation({
    mutationFn: () => {
      if (!canMutate()) throw new Error("لا يمكن التعديل بدون اتصال بـ FINORA.");
      return finora.products.adjustStock(
        product.id,
        direction * amount,
        reason,
        product.has_colors ? colorName : undefined,
      );
    },
    onSuccess: (result) => {
      toast.success(result.message);
      setConfirming(false);
      onDone();
    },
    onError: (error) => {
      setConfirming(false);
      toast.error(
        error instanceof Error && !("kind" in error) ? error.message : toFinoraError(error).message,
      );
    },
  });
  const current = product.has_colors
    ? (product.colors.find((c) => c.name === colorName)?.qty ?? 0)
    : product.current_stock;
  const next = current + direction * amount;

  return (
    <div className="space-y-3">
      {product.has_colors && (
        <Labeled label={product.option_axes?.length ? "خيار تعديل المخزون" : "لون تعديل المخزون"}>
          <select
            aria-label={product.option_axes?.length ? "خيار تعديل المخزون" : "لون تعديل المخزون"}
            value={colorName}
            onChange={(e) => setColorName(e.target.value)}
            className={inputBox}
          >
            {product.colors.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} — {formatNumber(c.qty)} قطعة
              </option>
            ))}
          </select>
        </Labeled>
      )}
      <div className="flex items-center gap-3">
        <div
          role="radiogroup"
          aria-label="اتجاه التعديل"
          className="flex rounded-control bg-surface-sunken p-1"
        >
          {([1, -1] as const).map((dir) => (
            <button
              key={dir}
              type="button"
              role="radio"
              aria-checked={direction === dir}
              onClick={() => setDirection(dir)}
              className={cn(
                "flex h-9 items-center gap-1.5 rounded-[10px] px-3 text-sm font-semibold transition-colors",
                direction === dir
                  ? dir === 1
                    ? "bg-success-soft text-success shadow-control"
                    : "bg-danger-soft text-danger shadow-control"
                  : "text-ink-soft",
              )}
            >
              {dir === 1 ? <Plus size={15} /> : <Minus size={15} />}
              {dir === 1 ? "إضافة" : "خصم"}
            </button>
          ))}
        </div>
        <input
          aria-label="كمية التعديل"
          dir="ltr"
          inputMode="numeric"
          value={amount}
          onFocus={(event) => event.target.select()}
          onChange={(event) => setAmount(Math.max(1, Number(event.target.value.replace(/\D/g, "")) || 1))}
          className={cn(inputBox, "ltr-isolate h-11 w-24 text-center font-semibold")}
        />
        <span className="text-sm text-ink-soft">
          المخزون بعد التعديل:{" "}
          <span className={cn("ltr-isolate font-bold", next < 0 ? "text-danger" : "text-ink")}>
            {formatNumber(next)}
          </span>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-ink-faint">السبب:</span>
        {STOCK_REASONS.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={reason === item}
            onClick={() => setReason(item)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium ring-1 transition-colors",
              reason === item
                ? "bg-violet-soft text-violet-deep ring-violet/25"
                : "text-ink-soft ring-line hover:bg-surface-sunken",
            )}
          >
            {item}
          </button>
        ))}
        <input
          aria-label="سبب آخر"
          value={STOCK_REASONS.includes(reason as (typeof STOCK_REASONS)[number]) ? "" : reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="سبب آخر…"
          className="h-8 w-36 rounded-full border border-line bg-white px-3 text-xs outline-none focus:border-violet/45"
        />
        <button
          type="button"
          disabled={next < 0 || !reason.trim() || adjust.isPending || (product.has_colors && !colorName)}
          onClick={() => setConfirming(true)}
          className="ms-auto flex h-9 items-center gap-1.5 rounded-control bg-ink px-4 text-sm font-semibold text-white disabled:opacity-40"
        >
          <RefreshCw size={14} aria-hidden />
          تطبيق على المخزون
        </button>
      </div>
      <ConfirmDialog
        open={confirming}
        title="تأكيد تعديل المخزون"
        message={`سيتم ${direction === 1 ? "إضافة" : "خصم"} ${formatNumber(amount)} من «${product.name}${product.has_colors ? ` — ${colorName}` : ""}» (${reason}). المخزون: ${formatNumber(current)} ← ${formatNumber(next)}. تُسجَّل كحركة مخزون في FINORA.`}
        confirmLabel="تطبيق"
        busy={adjust.isPending}
        onConfirm={() => adjust.mutate()}
        onClose={() => setConfirming(false)}
      />
    </div>
  );
}

interface ProductEditorProps {
  target: EditorTarget | null;
  categories: string[];
  brands: string[];
  serverUrl: string | null;
  onClose(): void;
}

/**
 * Add / edit product sheet. Creation goes through FINORA's own add-product
 * form; edits send only the changed fields, so specs, gallery, delivery fees
 * and colours set on the web stay intact.
 */
export function ProductEditor({ target, categories, brands, serverUrl, onClose }: ProductEditorProps) {
  const queryClient = useQueryClient();
  const canEditPrice = useCan("edit_price");
  const canAdjustStock = useCan("edit_current_stock");
  const editId = target?.kind === "edit" ? target.id : null;
  const details = useQuery({
    queryKey: ["products", "details", editId ?? 0],
    queryFn: () => finora.products.details(editId ?? 0),
    enabled: editId !== null,
    placeholderData: undefined,
  });
  const loading = editId !== null && !details.data && details.isLoading;
  // Never show an editable blank form for an existing product: a save would overwrite it.
  const loadFailed = editId !== null && !details.data && details.isError;
  const unavailable = loading || loadFailed;

  const [initial, setInitial] = useState<FormState>(EMPTY);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [optionsDraft, setOptionsDraft] = useState<OptionsDraft | null>(null);
  const addedColors = optionsDraft?.rows.filter((row) => !row.id) ?? [];
  const [colorPhotos, setColorPhotos] = useState<
    Record<string, { upload?: ImageUpload; preview?: string; remove?: boolean }>
  >({});
  const colorPhotosRef = useRef(colorPhotos);
  const photoGeneration = useRef(0);
  const [readingPhotos, setReadingPhotos] = useState(0);
  const clearColorPhotos = useCallback(() => {
    photoGeneration.current++;
    for (const photo of Object.values(colorPhotosRef.current))
      if (photo.preview) URL.revokeObjectURL(photo.preview);
    colorPhotosRef.current = {};
    setColorPhotos({});
  }, []);
  useEffect(
    () => () => {
      photoGeneration.current++;
      for (const photo of Object.values(colorPhotosRef.current))
        if (photo.preview) URL.revokeObjectURL(photo.preview);
    },
    [],
  );
  const [image, setImage] = useState<(ImageUpload & { preview: string }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const scrollBody = useRef<HTMLDivElement>(null);
  const loadedFor = useRef<number | null>(null);

  // Reset when the sheet opens for a new target; fill once FINORA's data arrives.
  useEffect(() => {
    clearColorPhotos();
    if (!target) return;
    loadedFor.current = null;
    if (target.kind === "create") {
      setInitial(EMPTY);
      setForm(EMPTY);
    } else {
      const cached = queryClient.getQueryData<ProductDetails>(["products", "details", target.id]);
      if (cached) {
        loadedFor.current = cached.id;
        const state = fromDetails(cached);
        setInitial(state);
        setForm(state);
      }
    }
    setImage(null);
    setOptionsDraft(null);
    setError(null);
    requestAnimationFrame(() => {
      scrollBody.current?.scrollTo({ top: 0 });
      nameInput.current?.focus({ preventScroll: true });
    });
  }, [target, queryClient, clearColorPhotos]);
  useEffect(() => {
    if (details.data && loadedFor.current !== details.data.id) {
      loadedFor.current = details.data.id;
      const state = fromDetails(details.data);
      setInitial(state);
      setForm(state);
    }
  }, [details.data]);
  useEffect(
    () => () => {
      if (image) URL.revokeObjectURL(image.preview);
    },
    [image],
  );

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  // A scan while the sheet is open fills the barcode field.
  useBarcodeScanner(
    useCallback((code: string) => setForm((f) => ({ ...f, barcode: code })), []),
    target !== null,
  );
  const dirty = useMemo(
    () =>
      JSON.stringify(form) !== JSON.stringify(initial) ||
      image !== null ||
      optionsDraft !== null ||
      Object.keys(colorPhotos).length > 0,
    [form, initial, image, optionsDraft, colorPhotos],
  );
  const margin = form.salePrice - form.buyPrice;
  const marginPct = form.buyPrice > 0 ? Math.round((margin / form.buyPrice) * 1000) / 10 : null;

  const takeFile = useCallback(async (file: File | undefined) => {
    if (!file) return;
    const allowed = ["image/png", "image/jpeg", "image/webp", "image/gif"] as const;
    const type = allowed.find((t) => t === file.type);
    if (!type) return setError("الصورة يجب أن تكون PNG أو JPG أو WEBP.");
    if (file.size > MAX_UPLOAD_BYTES) return setError("حجم الصورة أكبر من 8 ميغابايت.");
    const generation = photoGeneration.current;
    setReadingPhotos((count) => count + 1);
    try {
      const data = new Uint8Array(await file.arrayBuffer());
      if (generation !== photoGeneration.current) return;
      setImage({ name: file.name, type, data, preview: URL.createObjectURL(file) });
      setError(null);
    } catch {
      setError("تعذّر قراءة الصورة؛ اخترها مجدداً.");
    } finally {
      setReadingPhotos((count) => count - 1);
    }
  }, []);

  const save = useMutation({
    mutationFn: async (addAnother: boolean) => {
      if (!canMutate()) throw new Error("لا يمكن الحفظ بدون اتصال بـ FINORA.");
      const upload = image ? { name: image.name, type: image.type, data: image.data } : undefined;
      const colorImages: ColorImageChange[] = Object.entries(colorPhotos).map(([name, photo]) => ({
        name,
        ...(photo.upload ? { upload: photo.upload } : { remove: true }),
      }));
      if (
        (upload?.data.byteLength ?? 0) +
          colorImages.reduce((total, photo) => total + (photo.upload?.data.byteLength ?? 0), 0) >
        MAX_TOTAL_UPLOAD_BYTES
      )
        throw new Error("مجموع الصور لا يتجاوز 32 ميغابايت؛ اختر صوراً أصغر.");
      if (editId === null) {
        const result = await finora.products.create(
          {
            name: form.name.trim(),
            sku: form.sku.trim(),
            barcode: form.barcode.trim(),
            buy_price: form.buyPrice,
            sale_price: form.salePrice,
            exchange_sale_price: form.exchangePrice,
            pos_visible: form.posVisible,
            store_visible: form.storeVisible,
            low_stock_threshold: form.lowStock,
            category: form.category.trim(),
            brand: form.brand.trim(),
            unit: form.unit.trim(),
            description: form.description.trim(),
            active: form.active,
            opening_stock: addedColors.length
              ? addedColors.reduce((total, c) => total + c.qty, 0)
              : form.openingStock,
            colors: optionsDraft?.rows,
            product_options: optionsDraft ? JSON.stringify(optionsDraft) : undefined,
          },
          upload,
          colorImages,
        );
        return { addAnother, created: true, id: result.product_id };
      }
      await finora.products.update(
        editId,
        {
          ...changedFields(initial, form),
          ...(optionsDraft ? { product_options: JSON.stringify(optionsDraft) } : {}),
        },
        upload,
        colorImages,
      );
      return { addAnother: false, created: false, id: editId };
    },
    onSuccess: ({ addAnother, created }) => {
      toast.success(created ? `تمت إضافة «${form.name.trim()}»` : `تم حفظ تعديلات «${form.name.trim()}»`);
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      void queryClient.invalidateQueries({ queryKey: ["pos", "products"] });
      if (addAnother) {
        // keep classification for fast batch entry
        const keep = { ...EMPTY, category: form.category, brand: form.brand, unit: form.unit };
        setInitial(keep);
        setForm(keep);
        setOptionsDraft(null);
        clearColorPhotos();
        setImage(null);
        requestAnimationFrame(() => {
          scrollBody.current?.scrollTo({ top: 0 });
          nameInput.current?.focus({ preventScroll: true });
        });
      } else {
        onClose();
      }
    },
    onError: (failure) =>
      setError(
        failure instanceof Error && !("kind" in failure) ? failure.message : toFinoraError(failure).message,
      ),
  });

  const takeColorPhoto = async (name: string, file: File | null) => {
    if (save.isPending) return;
    const generation = photoGeneration.current;
    const allowed = ["image/png", "image/jpeg", "image/webp", "image/gif"] as const;
    const type = file && allowed.find((value) => value === file.type);
    if (file && !type) return setError("الصورة يجب أن تكون PNG أو JPG أو WEBP.");
    if (file && file.size > MAX_UPLOAD_BYTES) return setError("حجم الصورة أكبر من 8 ميغابايت.");
    setReadingPhotos((count) => count + 1);
    try {
      const data = file ? new Uint8Array(await file.arrayBuffer()) : null;
      if (generation !== photoGeneration.current) return;
      const previous = colorPhotosRef.current[name];
      if (previous?.preview) URL.revokeObjectURL(previous.preview);
      let next = { ...colorPhotosRef.current };
      if (file && type && data)
        next[name] = { upload: { name: file.name, type, data }, preview: URL.createObjectURL(file) };
      else if (details.data?.colors.some((color) => color.name === name && color.image_url))
        next[name] = { remove: true };
      else next = Object.fromEntries(Object.entries(next).filter(([key]) => key !== name));
      colorPhotosRef.current = next;
      setColorPhotos(next);
      setError(null);
    } catch {
      setError("تعذّر قراءة الصورة؛ اخترها مجدداً.");
    } finally {
      setReadingPhotos((count) => count - 1);
    }
  };

  const submit = useCallback(
    (addAnother: boolean) => {
      if (save.isPending || readingPhotos > 0 || unavailable) return;
      if (!form.name.trim()) {
        setError("يرجى إدخال اسم المنتج.");
        nameInput.current?.focus();
        return;
      }
      if (editId !== null && !dirty) {
        onClose();
        return;
      }
      setError(null);
      save.mutate(addAnother);
    },
    [save, readingPhotos, unavailable, form.name, editId, dirty, onClose],
  );

  const requestClose = useCallback(() => {
    if (dirty && !save.isPending) setConfirmDiscard(true);
    else onClose();
  }, [dirty, save.isPending, onClose]);

  useEffect(() => {
    if (!target) return;
    const onKey = (event: KeyboardEvent) => {
      if (document.querySelector('[aria-modal="true"], [data-popover]')) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        requestClose();
      } else if ((event.ctrlKey || event.metaKey) && (event.code === "KeyS" || event.key === "Enter")) {
        event.preventDefault();
        submit(false);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [target, requestClose, submit]);

  const currentImage =
    image?.preview ?? (details.data ? productImageUrl(details.data.image_url, serverUrl) : null);
  const priceLocked = editId !== null && !canEditPrice;
  const settingsSupported = editId === null || details.data?.editor_settings_supported === true;
  const exchangeEnabled = details.data?.trade_in_sales_enabled !== false;

  return (
    <AnimatePresence>
      {target && (
        <>
          <motion.div
            key="scrim"
            className="absolute inset-0 z-30 rounded-panel bg-ink/10"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onPointerDown={requestClose}
          />
          <motion.section
            key="sheet"
            role="dialog"
            aria-label={editId === null ? "منتج جديد" : "تعديل منتج"}
            className="glass-solid absolute inset-y-0 start-0 z-40 grid min-h-0 w-[min(640px,62%)] grid-rows-[auto_minmax(0,1fr)_auto] overflow-clip rounded-panel bg-[#fbfaff]"
            initial={{ opacity: 0, x: 48 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 36, transition: { duration: 0.16 } }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            style={{ willChange: "transform, opacity" }}
          >
            <header className="flex items-center gap-3 border-b border-line/70 px-5 py-3.5">
              <span className="grid h-10 w-10 place-items-center rounded-control bg-violet-soft text-violet-deep">
                {editId === null ? <PackagePlus size={20} aria-hidden /> : <Boxes size={20} aria-hidden />}
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-[17px] font-bold text-ink">
                  {editId === null ? "منتج جديد" : form.name || "تعديل منتج"}
                </h2>
                <p className="text-xs text-ink-faint">Ctrl+S للحفظ · Esc للإغلاق</p>
              </div>
              {editId !== null && (
                <IconButton
                  label="فتح في FINORA (المواصفات والمعرض والألوان)"
                  size="sm"
                  onClick={() => {
                    finora.products
                      .openInFinora(editId)
                      .catch((e: unknown) => toast.error(toFinoraError(e).message));
                  }}
                >
                  <ExternalLink size={15} />
                </IconButton>
              )}
              <IconButton label="إغلاق" size="sm" onClick={requestClose}>
                <X size={17} />
              </IconButton>
            </header>

            {loading ? (
              <div className="flex flex-1 items-center justify-center text-sm text-ink-faint">
                <Loader2 size={20} className="me-2 animate-spin" aria-hidden /> جارٍ تحميل المنتج من FINORA…
              </div>
            ) : loadFailed ? (
              <div
                role="alert"
                className="flex flex-1 flex-col items-center justify-center gap-3 px-8 text-center"
              >
                <span className="grid h-12 w-12 place-items-center rounded-full bg-danger-soft text-danger">
                  <AlertTriangle size={22} aria-hidden />
                </span>
                <p className="font-semibold text-ink">تعذر تحميل بيانات المنتج من FINORA</p>
                <p className="max-w-[380px] text-sm text-ink-soft">
                  {toFinoraError(details.error).kind === "not_found"
                    ? "المنتج غير موجود، أو أن خادم FINORA المتصل لم يُحدَّث بعد لدعم تعديل المنتجات من التطبيق. حدّث FINORA على الخادم أو عدّل المنتج من الموقع."
                    : toFinoraError(details.error).message}
                </p>
                <button
                  type="button"
                  onClick={() => void details.refetch()}
                  className="flex h-10 items-center gap-2 rounded-control bg-white px-4 text-sm font-semibold text-ink ring-1 ring-line hover:bg-surface-sunken"
                >
                  <RefreshCw size={15} aria-hidden />
                  إعادة المحاولة
                </button>
              </div>
            ) : (
              <div ref={scrollBody} className="min-h-0 space-y-3 overflow-y-auto overscroll-contain p-4">
                <div className="grid grid-cols-[150px_minmax(0,1fr)] gap-3">
                  <button
                    type="button"
                    aria-label="صورة المنتج"
                    onClick={() => fileInput.current?.click()}
                    onDragOver={(event: DragEvent) => {
                      event.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(event: DragEvent) => {
                      event.preventDefault();
                      setDragging(false);
                      void takeFile(event.dataTransfer.files[0]);
                    }}
                    className={cn(
                      "group relative grid aspect-square place-items-center overflow-hidden rounded-panel border-2 border-dashed transition-colors",
                      dragging
                        ? "border-violet bg-violet-soft"
                        : "border-line bg-white hover:border-violet/50",
                    )}
                  >
                    {currentImage ? (
                      <>
                        <img src={currentImage} alt="" className="h-full w-full object-cover" />
                        <span className="absolute inset-x-0 bottom-0 bg-ink/55 py-1.5 text-center text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                          تغيير الصورة
                        </span>
                      </>
                    ) : (
                      <span className="flex flex-col items-center gap-1.5 px-3 text-center text-xs text-ink-faint">
                        <ImagePlus size={26} className="text-violet" aria-hidden />
                        اسحب صورة هنا أو اضغط للاختيار
                      </span>
                    )}
                  </button>
                  <input
                    ref={fileInput}
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    className="hidden"
                    onChange={(event) => void takeFile(event.target.files?.[0])}
                  />
                  <div className="space-y-3">
                    <Labeled label="اسم المنتج" required>
                      <input
                        ref={nameInput}
                        aria-label="اسم المنتج"
                        value={form.name}
                        onChange={(e) => set("name", e.target.value)}
                        placeholder="مثال: شاشة LG 50 بوصة 4K"
                        className={inputBox}
                      />
                    </Labeled>
                    <div className="grid grid-cols-2 gap-3">
                      <Labeled label="SKU">
                        <input
                          aria-label="SKU"
                          dir="ltr"
                          value={form.sku}
                          onChange={(e) => set("sku", e.target.value)}
                          placeholder="TV-LG-50"
                          className={cn(inputBox, "ltr-isolate")}
                        />
                      </Labeled>
                      <Labeled
                        label="الباركود"
                        hint={
                          <button
                            type="button"
                            onClick={() => set("barcode", generateStoreBarcode())}
                            className="inline-flex items-center gap-1 text-violet-deep hover:underline"
                          >
                            <Wand2 size={12} aria-hidden /> توليد
                          </button>
                        }
                      >
                        <input
                          aria-label="الباركود"
                          dir="ltr"
                          value={form.barcode}
                          onChange={(e) => set("barcode", e.target.value.trim())}
                          placeholder="امسح أو اكتب"
                          className={cn(inputBox, "ltr-isolate")}
                        />
                      </Labeled>
                    </div>
                  </div>
                </div>

                <Section title="التصنيف" icon={Tag}>
                  <div className="grid grid-cols-3 gap-3">
                    <Labeled label="الفئة">
                      <input
                        aria-label="الفئة"
                        list="finora-categories"
                        value={form.category}
                        onChange={(e) => set("category", e.target.value)}
                        placeholder="شاشات"
                        className={inputBox}
                      />
                    </Labeled>
                    <Labeled label="الماركة">
                      <input
                        aria-label="الماركة"
                        list="finora-brands"
                        value={form.brand}
                        onChange={(e) => set("brand", e.target.value)}
                        placeholder="LG"
                        className={inputBox}
                      />
                    </Labeled>
                    <Labeled label="الوحدة">
                      <input
                        aria-label="الوحدة"
                        value={form.unit}
                        onChange={(e) => set("unit", e.target.value)}
                        placeholder="قطعة"
                        className={inputBox}
                      />
                    </Labeled>
                  </div>
                  <datalist id="finora-categories">
                    {categories.map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                  <datalist id="finora-brands">
                    {brands.map((b) => (
                      <option key={b} value={b} />
                    ))}
                  </datalist>
                </Section>

                <Section
                  title="الأسعار"
                  icon={TrendingUp}
                  aside={
                    priceLocked ? (
                      <span className="text-xs text-warning">لا تملك صلاحية تعديل الأسعار</span>
                    ) : form.salePrice > 0 || form.buyPrice > 0 ? (
                      <span
                        className={cn(
                          "rounded-full px-2.5 py-0.5 text-xs font-semibold",
                          margin < 0 ? "bg-danger-soft text-danger" : "bg-success-soft text-success",
                        )}
                      >
                        الربح{" "}
                        <span className="ltr-isolate">
                          {formatNumber(margin)}
                          {marginPct !== null ? ` · ${marginPct}%` : ""}
                        </span>
                      </span>
                    ) : null
                  }
                >
                  <div className="grid grid-cols-3 gap-3">
                    <Labeled label="سعر الشراء">
                      <MoneyField
                        label="سعر الشراء"
                        value={form.buyPrice}
                        onChange={(v) => set("buyPrice", v)}
                        disabled={priceLocked}
                      />
                    </Labeled>
                    <Labeled label="سعر البيع">
                      <MoneyField
                        label="سعر البيع"
                        value={form.salePrice}
                        onChange={(v) => set("salePrice", v)}
                        disabled={priceLocked}
                      />
                    </Labeled>
                    <Labeled label="أدنى مخزون" hint="للتنبيه">
                      <input
                        aria-label="أدنى مخزون"
                        dir="ltr"
                        inputMode="numeric"
                        value={form.lowStock}
                        onFocus={(e) => e.target.select()}
                        onChange={(e) => set("lowStock", Number(e.target.value.replace(/\D/g, "")) || 0)}
                        className={cn(inputBox, "ltr-isolate text-center")}
                      />
                    </Labeled>
                  </div>
                  <div className="mt-3">
                    <Labeled label="سعر الاستبدال" hint="اتركه فارغاً لإيقاف الاستبدال لهذا المنتج">
                      <MoneyField
                        label="سعر الاستبدال"
                        value={form.exchangePrice}
                        onChange={(v) => set("exchangePrice", v)}
                        disabled={priceLocked || !settingsSupported || !exchangeEnabled}
                      />
                    </Labeled>
                    {!exchangeEnabled && (
                      <p className="mt-2 text-xs text-ink-soft">ميزة الاستبدال غير مفعّلة لهذه الشركة.</p>
                    )}
                  </div>
                </Section>

                <Section title="خيارات المنتج" icon={Palette}>
                  <ProductOptions
                    key={`${editId ?? "create"}:${details.data?.id ?? "loading"}`}
                    existing={details.data?.colors ?? []}
                    axes={details.data?.option_axes ?? []}
                    value={optionsDraft}
                    onChange={(next) => {
                      const names = new Set(next?.rows.map((row) => row.name) ?? []);
                      const kept = Object.fromEntries(
                        Object.entries(colorPhotosRef.current).filter(([name, photo]) => {
                          if (names.has(name)) return true;
                          if (photo.preview) URL.revokeObjectURL(photo.preview);
                          return false;
                        }),
                      );
                      colorPhotosRef.current = kept;
                      setColorPhotos(kept);
                      setOptionsDraft(next);
                    }}
                    create={editId === null}
                    currentStock={details.data?.current_stock ?? 0}
                    openingStock={form.openingStock}
                    supported={editId === null || details.data?.options_supported === true}
                    photos={colorPhotos}
                    onPhotoChange={(name, file) => {
                      void takeColorPhoto(name, file);
                    }}
                    serverUrl={serverUrl}
                    busy={save.isPending || readingPhotos > 0}
                    priceLocked={priceLocked}
                  />
                </Section>

                <Section title="المخزون" icon={Boxes}>
                  {editId === null && addedColors.length > 0 ? (
                    <p className="text-sm text-ink-soft">
                      يُسجَّل المخزون الافتتاحي لكل خيار من قسم خيارات المنتج أعلاه.
                    </p>
                  ) : editId === null ? (
                    <Labeled label="المخزون الافتتاحي" hint="يُسجَّل لفرعك الحالي">
                      <input
                        aria-label="المخزون الافتتاحي"
                        dir="ltr"
                        inputMode="numeric"
                        value={form.openingStock}
                        onFocus={(e) => e.target.select()}
                        onChange={(e) => set("openingStock", Number(e.target.value.replace(/\D/g, "")) || 0)}
                        className={cn(inputBox, "ltr-isolate w-40 text-center font-semibold")}
                      />
                    </Labeled>
                  ) : addedColors.length > 0 ? (
                    <p className="text-sm text-ink-soft">
                      احفظ الخيارات أولاً، ثم عدّل مخزون كل خيار من هذه النافذة.
                    </p>
                  ) : details.data?.has_colors && !details.data.colors_supported ? (
                    <p className="text-sm text-ink-soft">
                      مخزون هذا المنتج حسب الخيار — يُعدَّل من صفحة المنتج في FINORA (زر ↗ في الأعلى).
                    </p>
                  ) : details.data ? (
                    <div className="space-y-3">
                      <p className="text-sm text-ink-soft">
                        المخزون الحالي:{" "}
                        <span className="ltr-isolate text-base font-bold text-ink">
                          {formatNumber(details.data.current_stock)}
                        </span>
                      </p>
                      {canAdjustStock ? (
                        <StockAdjuster
                          product={details.data}
                          onDone={() => {
                            void queryClient.invalidateQueries({ queryKey: ["products"] });
                            void queryClient.invalidateQueries({ queryKey: ["pos", "products"] });
                          }}
                        />
                      ) : (
                        <p className="text-xs text-warning">لا تملك صلاحية تعديل المخزون.</p>
                      )}
                    </div>
                  ) : null}
                </Section>

                <Section title="ظهور المنتج" icon={CheckCircle2}>
                  <p className="mb-3 text-xs text-ink-soft">إخفاء المنتج يبقيه في الجرد وسجلاته السابقة.</p>
                  <div className="space-y-3">
                    {(
                      [
                        ["posVisible", "إظهار في نقطة البيع"],
                        ["storeVisible", "إظهار في المتجر"],
                      ] as const
                    ).map(([key, label]) => (
                      <label key={key} className="flex items-center gap-3 text-sm">
                        <button
                          type="button"
                          role="switch"
                          aria-label={label}
                          aria-checked={form[key]}
                          disabled={!settingsSupported}
                          onClick={() => set(key, !form[key])}
                          className={cn(
                            "h-6 w-11 shrink-0 rounded-full p-0.5 transition-colors disabled:opacity-50",
                            form[key] ? "bg-success" : "bg-line",
                          )}
                        >
                          <span
                            className={cn(
                              "block h-5 w-5 rounded-full bg-white shadow transition-transform duration-200",
                              form[key] ? "-translate-x-5" : "translate-x-0",
                            )}
                          />
                        </button>
                        <span>{label}</span>
                        <span className="mr-auto text-xs text-ink-soft">{form[key] ? "ظاهر" : "مخفي"}</span>
                      </label>
                    ))}
                  </div>
                  {!settingsSupported && (
                    <p className="mt-3 text-xs text-warning">هذه الإعدادات تحتاج تحديث خادم FINORA.</p>
                  )}
                </Section>

                <Section title="الوصف والحالة" icon={CheckCircle2}>
                  <textarea
                    aria-label="الوصف"
                    rows={3}
                    value={form.description}
                    onChange={(e) => set("description", e.target.value)}
                    placeholder="وصف مختصر يظهر في المتجر والفاتورة…"
                    className="w-full resize-none rounded-control border border-line bg-white/95 px-3.5 py-2.5 text-sm leading-6 outline-none focus:border-violet/45 focus:ring-4 focus:ring-violet/10"
                  />
                  <label className="mt-3 flex items-center gap-3 text-sm">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={form.active}
                      aria-label="متاح للبيع"
                      onClick={() => set("active", !form.active)}
                      className={cn(
                        "h-6 w-11 rounded-full p-0.5 transition-colors",
                        form.active ? "bg-success" : "bg-line",
                      )}
                    >
                      <span
                        className={cn(
                          "block h-5 w-5 rounded-full bg-white shadow transition-transform duration-200",
                          form.active ? "-translate-x-5" : "translate-x-0",
                        )}
                      />
                    </button>
                    <span className="text-ink">{form.active ? "متاح للبيع" : "موقوف عن البيع"}</span>
                  </label>
                </Section>
              </div>
            )}

            <footer className="border-t border-line/70 bg-white/70 px-5 py-3">
              <AnimatePresence>
                {error && (
                  <motion.p
                    role="alert"
                    className="mb-2.5 rounded-control bg-danger-soft px-3.5 py-2 text-sm text-danger"
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                  >
                    {error}
                  </motion.p>
                )}
              </AnimatePresence>
              <div className="flex items-center gap-2.5">
                {editId === null && (
                  <button
                    type="button"
                    disabled={save.isPending}
                    onClick={() => submit(true)}
                    className="h-11 rounded-control bg-white px-4 text-sm font-semibold text-ink ring-1 ring-line transition-colors hover:bg-surface-sunken disabled:opacity-50"
                  >
                    حفظ وإضافة آخر
                  </button>
                )}
                <button
                  type="button"
                  disabled={save.isPending || readingPhotos > 0 || unavailable || (editId !== null && !dirty)}
                  onClick={() => submit(false)}
                  className="ms-auto flex h-11 items-center gap-2 rounded-control bg-gradient-to-l from-violet to-violet-deep px-6 text-[15px] font-bold text-white shadow-float transition-opacity disabled:opacity-50"
                >
                  {save.isPending ? (
                    <Loader2 size={17} className="animate-spin" aria-hidden />
                  ) : (
                    <CheckCircle2 size={17} aria-hidden />
                  )}
                  {save.isPending ? "جارٍ الحفظ…" : editId === null ? "حفظ المنتج" : "حفظ التعديلات"}
                </button>
              </div>
            </footer>

            <ConfirmDialog
              open={confirmDiscard}
              title="تجاهل التغييرات؟"
              message="لديك تغييرات غير محفوظة على هذا المنتج."
              confirmLabel="تجاهل وإغلاق"
              tone="danger"
              onConfirm={() => {
                setConfirmDiscard(false);
                onClose();
              }}
              onClose={() => setConfirmDiscard(false)}
            />
          </motion.section>
        </>
      )}
    </AnimatePresence>
  );
}
