import { ImagePlus, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { productImageUrl } from "@/api/finora/products";
import { formatNumber } from "@/utils/format";

export interface ColorDraft {
  name: string;
  qty: number;
  image_url?: string;
}
export interface ColorPhotoDraft {
  preview?: string;
  remove?: boolean;
}
const SUGGESTIONS = ["أبيض", "أسود", "فضي", "رمادي", "أحمر", "أزرق", "ذهبي", "بيج"];
const SWATCHES: Record<string, string> = {
  أبيض: "#fff",
  أسود: "#292633",
  فضي: "#c3c7cf",
  رمادي: "#9295a0",
  أحمر: "#cb4265",
  أزرق: "#5477cf",
  ذهبي: "#d7b35a",
  بيج: "#dfccb0",
  أخضر: "#30a681",
};

export function ProductColors({
  existing,
  added,
  onChange,
  create,
  currentStock,
  openingStock,
  supported,
  photos = {},
  onPhotoChange,
  imagesSupported = false,
  serverUrl = null,
  busy = false,
}: {
  existing: ColorDraft[];
  added: ColorDraft[];
  onChange(colors: ColorDraft[]): void;
  create: boolean;
  currentStock: number;
  openingStock: number;
  supported: boolean;
  photos?: Record<string, ColorPhotoDraft>;
  onPhotoChange?(name: string, file: File | null): void;
  imagesSupported?: boolean;
  serverUrl?: string | null;
  busy?: boolean;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const colors = [...existing, ...added];
  const add = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || trimmed.length > 80) return setError("أدخل اسم لون من 1 إلى 80 حرفاً.");
    if (colors.some((c) => c.name.toLocaleLowerCase() === trimmed.toLocaleLowerCase()))
      return setError("هذا اللون مضاف مسبقاً.");
    if (colors.length >= 40) return setError("الحد الأقصى 40 لوناً للمنتج.");
    onChange([...added, { name: trimmed, qty: !colors.length ? (create ? openingStock : currentStock) : 0 }]);
    setName("");
    setError("");
  };
  return (
    <div className="space-y-3">
      <p className="text-xs leading-6 text-ink-soft">
        لكل لون مخزونه وصورته الخاصة. تتغيّر صورة المنتج في المتجر عند اختيار اللون.
      </p>
      {!supported ? (
        <p className="rounded-control bg-warning-soft p-3 text-xs text-warning">
          إضافة الألوان تحتاج تحديث خادم FINORA. يمكنك متابعة تعديل بقية بيانات المنتج.
        </p>
      ) : (
        <>
          <div className="flex gap-2">
            <input
              aria-label="اسم اللون"
              value={name}
              maxLength={80}
              onChange={(e) => {
                setName(e.target.value);
                setError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add(name);
                }
              }}
              placeholder="اسم اللون، مثل أبيض أو ستيل…"
              className="h-10 min-w-0 flex-1 rounded-control border border-line bg-white px-3 text-sm outline-none focus:border-violet/45 focus:ring-4 focus:ring-violet/10"
            />
            <button
              type="button"
              onClick={() => add(name)}
              disabled={!name.trim()}
              className="flex items-center gap-1.5 rounded-control bg-violet-soft px-3 text-sm font-semibold text-violet-deep disabled:opacity-40"
            >
              <Plus size={16} />
              إضافة لون
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.filter((s) => !colors.some((c) => c.name === s)).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => add(s)}
                className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-ink-soft ring-1 ring-line hover:bg-violet-soft"
              >
                <span
                  aria-hidden
                  className="h-3 w-3 rounded-full ring-1 ring-black/10"
                  style={{ background: SWATCHES[s] }}
                />
                {s}
              </button>
            ))}
          </div>
        </>
      )}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      {colors.length > 0 && (
        <div className="space-y-2">
          {colors.map((color, index) => {
            const draftIndex = index - existing.length;
            const photo = photos[color.name];
            const preview = photo?.remove
              ? null
              : (photo?.preview ?? productImageUrl(color.image_url ?? "", serverUrl));
            return (
              <div
                key={color.name}
                className="flex items-center gap-3 rounded-control border border-line/70 bg-surface-sunken/50 px-3 py-2"
              >
                {imagesSupported && onPhotoChange && (
                  <label
                    title={preview ? "تغيير الصورة" : "إضافة صورة"}
                    className="group relative flex h-14 w-14 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-control border border-line bg-white text-violet hover:border-violet/50"
                  >
                    {preview ? (
                      <img
                        src={preview}
                        alt={`صورة ${color.name}`}
                        className="h-full w-full object-contain"
                      />
                    ) : (
                      <ImagePlus size={22} />
                    )}
                    <input
                      type="file"
                      aria-label={`صورة اللون ${color.name}`}
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      disabled={busy}
                      className="sr-only"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) onPhotoChange(color.name, file);
                        event.target.value = "";
                      }}
                    />
                  </label>
                )}
                <div className="min-w-0 flex-1">
                  <span className="flex items-center gap-2 text-sm font-semibold text-ink">
                    <span
                      aria-hidden
                      className="h-3 w-3 shrink-0 rounded-full ring-1 ring-black/10"
                      style={{ background: SWATCHES[color.name] ?? "#ae98dd" }}
                    />
                    <span className="truncate">{color.name}</span>
                  </span>
                  {imagesSupported && (
                    <span className="mt-1 block text-xs text-ink-soft">
                      {preview ? "تظهر عند اختيار اللون" : "تستخدم صورة المنتج حتى تضيف صورة"}
                    </span>
                  )}
                </div>
                {create ? (
                  <label className="flex items-center gap-2 text-xs text-ink-soft">
                    المخزون
                    <input
                      aria-label={`مخزون ${color.name}`}
                      inputMode="numeric"
                      dir="ltr"
                      value={color.qty}
                      onFocus={(e) => e.target.select()}
                      onChange={(e) =>
                        onChange(
                          added.map((c, i) =>
                            i === draftIndex
                              ? { ...c, qty: Number(e.target.value.replace(/\D/g, "")) || 0 }
                              : c,
                          ),
                        )
                      }
                      className="h-8 w-20 rounded-control border border-line bg-white text-center text-sm font-semibold outline-none focus:border-violet/45"
                    />
                  </label>
                ) : (
                  <span className="text-xs text-ink-soft">{formatNumber(color.qty)} قطعة</span>
                )}
                {preview && imagesSupported && onPhotoChange && (
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`إزالة صورة ${color.name}`}
                    title={`إزالة صورة ${color.name}`}
                    onClick={() => onPhotoChange(color.name, null)}
                    className="rounded-control p-1.5 text-ink-faint hover:bg-danger-soft hover:text-danger"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
                {draftIndex >= 0 && (
                  <button
                    type="button"
                    aria-label={`إزالة لون ${color.name}`}
                    title={`إزالة لون ${color.name}`}
                    disabled={busy}
                    onClick={() =>
                      onChange(
                        added
                          .filter((_, i) => i !== draftIndex)
                          .map((c, i) =>
                            !create && !existing.length && i === 0
                              ? { ...c, qty: currentStock }
                              : !create
                                ? { ...c, qty: 0 }
                                : c,
                          ),
                      )
                    }
                    className="rounded-control p-1.5 text-ink-faint hover:bg-danger-soft hover:text-danger"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
      {!create && !existing.length && added.length > 0 && (
        <p className="rounded-control bg-violet-soft px-3 py-2 text-xs leading-6 text-violet-deep">
          سيُربط المخزون الحالي ({formatNumber(currentStock)} قطعة) بلون «{added[0]?.name}». تبدأ الألوان
          الأخرى برصيد صفر، ويمكن تعديل مخزونها بعد الحفظ.
        </p>
      )}
      {create && added.length > 0 && (
        <p className="text-xs text-ink-soft">
          إجمالي المخزون الافتتاحي:{" "}
          <strong className="text-ink">{formatNumber(added.reduce((total, c) => total + c.qty, 0))}</strong>
        </p>
      )}
    </div>
  );
}
