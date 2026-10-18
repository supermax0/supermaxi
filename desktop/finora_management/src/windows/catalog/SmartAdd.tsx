import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { CatalogEntryInput } from "@/api/finora/catalog";
import { Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

/** Barcode / model → what we already know (catalogue, inventory, configured sources). Saving is a separate step. */
export function SmartAdd({
  onCreate,
  onOpen,
}: {
  onCreate(data: Partial<CatalogEntryInput>): void;
  onOpen(id: number): void;
}) {
  const [q, setQ] = useState("");
  const lookup = useMutation({ mutationFn: (text: string) => finora.catalog.lookup(text) });
  const data = lookup.data;
  const looksLikeBarcode = /^\d{8,}$/.test(q.trim());

  return (
    <div className="space-y-4">
      <Panel title="إضافة منتج ذكي">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim().length >= 3) lookup.mutate(q.trim());
          }}
        >
          <input
            autoFocus
            aria-label="الباركود أو رقم الموديل"
            className={supplierInput}
            placeholder="امسح الباركود أو اكتب رقم الموديل"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            dir="ltr"
          />
          <button
            type="submit"
            className={supplierPrimary}
            disabled={lookup.isPending || q.trim().length < 3}
          >
            بحث
          </button>
        </form>
        <p className="mt-2 text-[12px] text-ink-faint">
          لا يُحفظ شيء في هذه الخطوة. البيانات غير المؤكدة تُحفظ «تحتاج مراجعة» ولا تُنشر.
        </p>
        {lookup.error && <p className="mt-2 text-sm text-danger">{toFinoraError(lookup.error).message}</p>}
      </Panel>

      {data && (
        <>
          {data.catalog.length > 0 && (
            <Panel title="موجود في كتالوج الشركة">
              <ul className="space-y-1.5 text-[13px]">
                {data.catalog.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-2">
                    <span>
                      {e.canonical_name}{" "}
                      <span className="text-ink-faint" dir="ltr">
                        {e.model_number}
                      </span>
                    </span>
                    <button type="button" className={supplierSecondary} onClick={() => onOpen(e.id)}>
                      فتح
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          {data.inventory && (
            <Panel title="موجود في المخزون">
              <p className="text-[13px]">
                {data.inventory.name}{" "}
                <span className="text-ink-faint" dir="ltr">
                  {data.inventory.sku || data.inventory.barcode}
                </span>
              </p>
              <button
                type="button"
                className={`${supplierSecondary} mt-2`}
                onClick={() =>
                  onCreate({
                    canonical_name: data.inventory?.name ?? "",
                    model_number: data.inventory?.sku ?? "",
                    barcodes: data.inventory?.barcode ? [data.inventory.barcode] : [],
                    verification_status: "needs_review",
                  })
                }
              >
                أنشئ موديلاً من بيانات المنتج
              </button>
            </Panel>
          )}
          {data.candidates.length > 0 && (
            <Panel title="نتائج من المصادر المفعّلة">
              <ul className="space-y-2 text-[13px]">
                {data.candidates.map((c, i) => (
                  <li key={i} className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      {String(c.canonical_name ?? "")} · {String(c.provider ?? "")}{" "}
                      {c.confidence !== undefined && (
                        <span className="text-ink-faint">({String(c.confidence)}%)</span>
                      )}
                    </span>
                    <button
                      type="button"
                      className={supplierSecondary}
                      onClick={() =>
                        onCreate({
                          canonical_name: String(c.canonical_name ?? ""),
                          brand: String(c.brand ?? ""),
                          model_number: String(c.model_number ?? ""),
                          verification_status: "needs_review",
                        })
                      }
                    >
                      راجع واحفظ
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          {data.catalog.length === 0 && !data.inventory && data.candidates.length === 0 && (
            <Panel title="لا توجد بيانات معروفة">
              <p className="mb-2 text-[13px] text-ink-soft">
                لم نجد هذا {looksLikeBarcode ? "الباركود" : "الموديل"} في الكتالوج أو المخزون، ولا مصدر خارجي
                مفعّل.
              </p>
              <button
                type="button"
                className={supplierPrimary}
                onClick={() =>
                  onCreate(
                    looksLikeBarcode
                      ? { barcodes: [q.trim()], verification_status: "needs_review" }
                      : { model_number: q.trim(), verification_status: "needs_review" },
                  )
                }
              >
                إدخال يدوي
              </button>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
