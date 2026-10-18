import { ImagePlus, Plus, X } from "lucide-react";
import { useState } from "react";
import { productImageUrl, type ProductDetails } from "@/api/finora/products";
import { FeatureHelp } from "@/components/FeatureHelp";
import type { ColorPhotoDraft } from "./ProductColors";
import { formatNumber } from "@/utils/format";

export interface OptionRow {
  id?: number;
  name: string;
  attributes: Record<string, string>;
  qty: number;
  active: boolean;
  image_url?: string;
  buy_price: number | null;
  sale_price: number | null;
  governorate_sale_price?: number | null;
  source_id?: number;
}
export interface OptionsDraft {
  axes: string[];
  rows: OptionRow[];
  expected_stock: number;
}

export function ProductOptions({
  existing,
  axes: savedAxes,
  value,
  onChange,
  create,
  currentStock,
  openingStock,
  supported,
  photos,
  onPhotoChange,
  serverUrl,
  busy,
  priceLocked,
}: {
  existing: ProductDetails["colors"];
  axes: string[];
  value: OptionsDraft | null;
  onChange(value: OptionsDraft | null): void;
  create: boolean;
  currentStock: number;
  openingStock: number;
  supported: boolean;
  photos: Record<string, ColorPhotoDraft>;
  onPhotoChange(name: string, file: File | null): void;
  serverUrl: string | null;
  busy: boolean;
  priceLocked: boolean;
}) {
  const [enabled, setEnabled] = useState(existing.length > 0);
  const [axisName, setAxisName] = useState("");
  const [attributes, setAttributes] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const axes = value?.axes ?? (savedAxes.length ? savedAxes : ["اللون"]);
  const rows: OptionRow[] =
    value?.rows ??
    existing.map((row) => ({
      ...row,
      attributes: row.attributes ?? { اللون: row.name },
      active: row.active ?? true,
      buy_price: row.buy_price ?? null,
      sale_price: row.sale_price ?? null,
    }));
  const change = (nextRows: OptionRow[], nextAxes = axes) =>
    onChange({ axes: nextAxes, rows: nextRows, expected_stock: currentStock });
  const update = (index: number, patch: Partial<OptionRow>) =>
    change(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  const addAxis = (name: string) => {
    const next = name.trim();
    if (!next || axes.includes(next) || axes.length >= 4) return;
    change(
      rows.map((row) => ({
        ...row,
        attributes: { ...row.attributes, [next]: "غير محدد" },
        active: row.id ? false : row.active,
      })),
      [...axes, next],
    );
    setAxisName("");
  };
  const add = () => {
    const attrs = Object.fromEntries(axes.map((axis) => [axis, (attributes[axis] ?? "").trim()]));
    if (Object.values(attrs).some((v) => !v)) return setError("أدخل قيمة لكل صفة أولاً.");
    const name =
      axes.length === 1 && axes[0] === "اللون"
        ? (attrs["اللون"] ?? "")
        : axes.map((axis) => `${axis}: ${attrs[axis]}`).join(" / ");
    if (name.length > 80) return setError("اختصر قيم الصفات؛ اسم الخيار لا يتجاوز 80 حرفاً.");
    if (rows.length >= 40 || rows.some((r) => r.name.toLocaleLowerCase() === name.toLocaleLowerCase()))
      return setError("الخيار مكرر أو وصل العدد إلى 40 خياراً.");
    change([
      ...rows,
      {
        name,
        attributes: attrs,
        qty: !rows.length ? (create ? openingStock : currentStock) : 0,
        active: true,
        buy_price: null,
        sale_price: null,
      },
    ]);
    setAttributes({});
    setError("");
  };
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 rounded-control bg-violet-soft/60 p-3">
        <label className="flex items-center gap-2 text-sm font-semibold text-ink">
          <input
            type="checkbox"
            checked={enabled || rows.length > 0}
            disabled={busy || existing.length > 0 || !supported}
            onChange={(event) => {
              setEnabled(event.target.checked);
              if (!event.target.checked) onChange(null);
              else change(rows);
            }}
          />
          هذا المنتج عنده خيارات
        </label>
        <FeatureHelp text="اختياري: فعّله إذا المنتج يأتي بأحجام أو مقاسات أو ألوان مختلفة. كل تركيبة لها صورة وسعر ومخزون مستقل، وتظهر بالمشتريات والطلبات والفواتير." />
      </div>
      {!supported && <p className="text-xs text-warning">خيارات المنتج تحتاج تحديث خادم FINORA.</p>}
      {(enabled || rows.length > 0) && supported && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-ink-soft">صفات المنتج</span>
            <FeatureHelp text="اختَر الصفات اللازمة فقط. العطر يمكن أن يحتوي على الحجم وحده. الملابس يمكن أن تحتوي على اللون والمقاس. يمكنك اختيار أي صفة أولاً بالمتجر." />
            {axes.map((axis) => (
              <span
                key={axis}
                className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-xs ring-1 ring-line"
              >
                {axis}
                {!rows.length && (
                  <button
                    type="button"
                    aria-label={`إزالة صفة ${axis}`}
                    disabled={axes.length === 1}
                    onClick={() =>
                      change(
                        [],
                        axes.filter((a) => a !== axis),
                      )
                    }
                  >
                    <X size={13} />
                  </button>
                )}
              </span>
            ))}
          </div>
          {!rows.length && (
            <div className="flex flex-wrap gap-2">
              {["اللون", "المقاس", "الحجم", "السعة"].map((axis) => (
                <button
                  key={axis}
                  type="button"
                  disabled={busy}
                  onClick={() => change([], [axis])}
                  className="rounded-control border border-line px-3 py-1.5 text-xs hover:bg-violet-soft"
                >
                  {axis} فقط
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <input
              aria-label="اسم صفة جديدة"
              value={axisName}
              maxLength={24}
              onChange={(event) => setAxisName(event.target.value)}
              placeholder="صفة إضافية، مثل المقاس أو الحجم"
              className="h-10 min-w-0 flex-1 rounded-control border border-line bg-white px-3 text-sm"
            />
            <button
              type="button"
              disabled={busy || !axisName.trim() || axes.length >= 4}
              onClick={() => addAxis(axisName)}
              className="rounded-control bg-violet-soft px-3 text-xs text-violet-deep"
            >
              إضافة صفة
            </button>
          </div>
          <div className="grid gap-2 rounded-control border border-dashed border-violet/30 p-3 sm:grid-cols-2">
            {axes.map((axis) => (
              <label key={axis} className="space-y-1 text-xs text-ink-soft">
                {axis}
                <input
                  aria-label={`قيمة ${axis}`}
                  maxLength={32}
                  value={attributes[axis] ?? ""}
                  onChange={(event) => setAttributes({ ...attributes, [axis]: event.target.value })}
                  placeholder={
                    axis === "المقاس" ? "مثلاً M أو 42" : axis === "الحجم" ? "مثلاً 50 مل" : `قيمة ${axis}`
                  }
                  className="block h-10 w-full rounded-control border border-line bg-white px-3 text-sm text-ink"
                />
              </label>
            ))}
            <button
              type="button"
              disabled={busy}
              onClick={add}
              className="flex h-10 items-center justify-center gap-2 self-end rounded-control bg-violet px-3 text-sm font-semibold text-white"
            >
              <Plus size={16} />
              إضافة خيار
            </button>
          </div>
          {error && (
            <p role="alert" className="text-xs text-danger">
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-3 text-xs text-ink-soft">
            <span>
              الصورة{" "}
              <FeatureHelp text="تظهر الصورة عند اختيار هذا الخيار بالمتجر. إذا لم تضف صورة يستخدم صورة المنتج الأساسية." />
            </span>
            <span>
              الأسعار{" "}
              <FeatureHelp text="اترك الحقل فارغاً لاستخدام سعر المنتج الأساسي. سعر الشراء للمشتريات والكلفة، وسعر البيع للمتجر والفاتورة." />
            </span>
            <span>
              المخزون{" "}
              <FeatureHelp text="تعديل بيانات الخيار لا يغيّر مخزونه. أضف الكميات بالمشتريات أو تعديل المخزون. عند تحويل منتج عادي وزّع رصيده الحالي بالكامل؛ ويمكن توزيع رصيد خيار قديم على خيارات جديدة دون زيادة الإجمالي." />
            </span>
            <span>
              الظهور{" "}
              <FeatureHelp text="إيقاف العرض يمنع اختيار هذا الخيار في المعاملات الجديدة ويحافظ على الفواتير والمرتجعات القديمة." />
            </span>
          </div>
          {rows.map((row, index) => {
            const photo = photos[row.name];
            const preview = photo?.remove
              ? null
              : (photo?.preview ?? productImageUrl(row.image_url ?? "", serverUrl));
            const editableQty = !row.id && (create || !existing.length || !!row.source_id);
            return (
              <div
                key={row.name}
                className="space-y-3 rounded-panel border border-line bg-surface-sunken/40 p-3"
              >
                <div className="flex items-center gap-3">
                  <label className="grid h-16 w-16 shrink-0 cursor-pointer place-items-center overflow-hidden rounded-control border border-line bg-white text-violet">
                    {preview ? (
                      <img src={preview} alt={`صورة ${row.name}`} className="h-full w-full object-contain" />
                    ) : (
                      <ImagePlus size={22} />
                    )}
                    <input
                      type="file"
                      className="sr-only"
                      aria-label={`صورة ${row.name}`}
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      disabled={busy}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) onPhotoChange(row.name, file);
                        event.target.value = "";
                      }}
                    />
                  </label>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold text-ink">{row.name}</p>
                    <p className="mt-1 text-xs text-ink-soft">
                      {formatNumber(row.qty)} قطعة · {preview ? "صورة خاصة" : "صورة المنتج الأساسية"}
                    </p>
                    {preview && (
                      <button
                        type="button"
                        aria-label={`إزالة صورة ${row.name}`}
                        disabled={busy}
                        onClick={() => onPhotoChange(row.name, null)}
                        className="mt-1 text-xs text-danger"
                      >
                        إزالة الصورة
                      </button>
                    )}
                  </div>
                  <label className="flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={row.active}
                      disabled={busy}
                      onChange={(event) => update(index, { active: event.target.checked })}
                    />
                    عرض
                  </label>
                  {!row.id && (
                    <button
                      type="button"
                      aria-label={`إزالة خيار ${row.name}`}
                      disabled={busy}
                      onClick={() => change(rows.filter((_, i) => i !== index))}
                      className="p-1 text-danger"
                    >
                      <X size={16} />
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {(["buy_price", "sale_price"] as const).map((key) => (
                    <label key={key} className="text-xs text-ink-soft">
                      {key === "buy_price" ? "سعر الشراء" : "سعر البيع"}
                      <input
                        type="number"
                        min="0"
                        step="1"
                        dir="ltr"
                        aria-label={`${key === "buy_price" ? "سعر شراء" : "سعر بيع"} ${row.name}`}
                        value={row[key] ?? ""}
                        placeholder="سعر المنتج"
                        disabled={busy || priceLocked}
                        onChange={(event) =>
                          update(index, {
                            [key]: event.target.value === "" ? null : Number(event.target.value),
                          })
                        }
                        className="mt-1 h-9 w-full rounded-control border border-line bg-white px-2 text-center text-sm"
                      />
                    </label>
                  ))}
                  <label className="text-xs text-ink-soft">
                    {row.source_id ? "كمية التوزيع" : "المخزون"}
                    <input
                      type="number"
                      min="0"
                      step="1"
                      dir="ltr"
                      aria-label={`مخزون ${row.name}`}
                      value={row.qty}
                      disabled={busy || !editableQty}
                      onChange={(event) => update(index, { qty: Number(event.target.value) })}
                      className="mt-1 h-9 w-full rounded-control border border-line bg-white px-2 text-center text-sm disabled:bg-surface-sunken"
                    />
                  </label>
                </div>
                {!row.id && existing.length > 0 && (
                  <label className="block text-xs text-ink-soft">
                    توزيع من مخزون موجود (اختياري)
                    <select
                      aria-label={`مصدر مخزون ${row.name}`}
                      value={row.source_id ?? ""}
                      disabled={busy}
                      onChange={(event) =>
                        update(index, {
                          source_id: event.target.value ? Number(event.target.value) : undefined,
                          qty: 0,
                        })
                      }
                      className="mt-1 h-9 w-full rounded-control border border-line bg-white px-2 text-sm"
                    >
                      <option value="">يبدأ بصفر — استلام بالمشتريات لاحقاً</option>
                      {existing
                        .filter((source) => source.id && source.qty > 0)
                        .map((source) => (
                          <option key={source.id} value={source.id}>
                            {source.name} — {formatNumber(source.qty)} قطعة
                          </option>
                        ))}
                    </select>
                  </label>
                )}
              </div>
            );
          })}
          {rows.length > 0 && !existing.length && (
            <p className="rounded-control bg-violet-soft p-3 text-xs text-violet-deep">
              إجمالي الخيارات: {formatNumber(rows.reduce((sum, row) => sum + row.qty, 0))} قطعة
              {!create && ` · المطلوب توزيع ${formatNumber(currentStock)} قطعة من المخزون الحالي`}
            </p>
          )}
        </>
      )}
    </div>
  );
}
