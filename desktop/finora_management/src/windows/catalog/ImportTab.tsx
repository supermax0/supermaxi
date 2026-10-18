import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { CatalogFile, ImportBatch } from "@/api/finora/catalog";
import { toast } from "@/stores/toasts";
import { Panel } from "../shipping/shared";
import { supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

const STATUS: Record<string, string> = {
  new: "جديد",
  matched: "موجود — يُكمَّل الناقص فقط",
  linked: "مطابق لمنتج بالمخزون",
  duplicate: "مكرر في الملف",
  needs_review: "يحتاج مراجعة",
  invalid: "غير صالح",
};
const TYPES: Record<string, CatalogFile["type"]> = {
  csv: "text/csv",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

/** Supplier list → preview with a verdict per row → apply once. Prices and quantities in the file are ignored. */
export function ImportTab({ onOpen }: { onOpen(id: number): void }) {
  const client = useQueryClient();
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [includeReview, setIncludeReview] = useState(false);
  const upload = useMutation({
    mutationFn: (file: CatalogFile) => finora.catalog.importFile(file),
    onSuccess: (res) => setBatch(res.batch),
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const apply = useMutation({
    mutationFn: () => finora.catalog.applyImport((batch as ImportBatch).id, includeReview),
    onSuccess: async (res) => {
      const r = res.result;
      toast.success(`أُضيف ${r.created} · اكتمل ${r.updated} · رُبط ${r.linked} · تُرك ${r.skipped}`);
      setBatch({ ...(batch as ImportBatch), status: "applied" });
      await client.invalidateQueries({ queryKey: ["catalog"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const pick = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    const type = TYPES[ext];
    if (!type) {
      toast.error("الملفات المدعومة: Excel (.xlsx) أو CSV");
      return;
    }
    upload.mutate({ name: file.name, type, data: new Uint8Array(await file.arrayBuffer()) });
  };

  return (
    <div className="space-y-4">
      <Panel title="استيراد قائمة مورد">
        <p className="mb-3 text-[13px] text-ink-soft">
          الأعمدة المعروفة: الاسم، العلامة، الموديل، الباركود، القسم، الوصف، رابط الصورة. أي عمود آخر يُحفظ
          كمواصفة. الأسعار والكميات في الملف تُتجاهل (الكتالوج لا يحمل سعراً ولا مخزوناً).
        </p>
        <label className={`${supplierPrimary} inline-flex cursor-pointer`}>
          {upload.isPending ? "جارٍ التحليل…" : "اختر ملف Excel أو CSV"}
          <input
            type="file"
            accept=".xlsx,.csv"
            className="sr-only"
            onChange={(e) => void pick(e.target.files)}
          />
        </label>
      </Panel>

      {batch && (
        <Panel title={`معاينة: ${batch.filename}`}>
          <div className="mb-3 flex flex-wrap gap-2 text-[12.5px]">
            {Object.entries(batch.counts).map(([k, n]) => (
              <span key={k} className="rounded-full bg-white px-3 py-1 ring-1 ring-line/60">
                {STATUS[k] ?? k}: {n}
              </span>
            ))}
          </div>
          <div className="max-h-[360px] overflow-auto rounded-lg ring-1 ring-line/60">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="p-2 text-start">#</th>
                  <th className="p-2 text-start">الاسم</th>
                  <th className="p-2 text-start">الموديل</th>
                  <th className="p-2 text-start">الحالة</th>
                  <th className="p-2 text-start">ملاحظات</th>
                </tr>
              </thead>
              <tbody>
                {batch.rows.map((r) => (
                  <tr key={r.id} className="border-t border-line/50">
                    <td className="p-2">{r.row_no}</td>
                    <td className="p-2">{String(r.data.name ?? "")}</td>
                    <td className="p-2" dir="ltr">
                      {String(r.data.model_number ?? "")}
                    </td>
                    <td className="p-2">{STATUS[r.status] ?? r.status}</td>
                    <td className="p-2 text-ink-soft">
                      {r.issues.join("، ")}
                      {r.applied_entry_id && (
                        <button
                          type="button"
                          className="ms-2 text-violet-deep underline"
                          onClick={() => onOpen(r.applied_entry_id as number)}
                        >
                          فتح
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {batch.status === "preview" ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={includeReview}
                  onChange={(e) => setIncludeReview(e.target.checked)}
                />{" "}
                أضف أيضاً الصفوف التي تحتاج مراجعة
              </label>
              <button
                type="button"
                className={supplierPrimary}
                disabled={apply.isPending}
                onClick={() => apply.mutate()}
              >
                تنفيذ الاستيراد
              </button>
              <button type="button" className={supplierSecondary} onClick={() => setBatch(null)}>
                إلغاء
              </button>
            </div>
          ) : (
            <p className="mt-3 text-[13px] text-ink-soft">
              نُفّذت هذه الدفعة. الموديلات الجديدة بحالة «يحتاج مراجعة» ولا تُنشر قبل توثيقها.
            </p>
          )}
        </Panel>
      )}
    </div>
  );
}
