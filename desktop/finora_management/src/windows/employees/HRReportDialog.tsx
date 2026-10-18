import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import type { HRTab } from "@/api/finora/hr";
import type { ReportQuery } from "@shared/ipc";
import { useConnection } from "@/stores/connection";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import { hrInput, hrPrimary } from "./shared";

export function HRReportDialog({
  tab,
  query,
  onClose,
}: {
  tab: HRTab | "commissions" | "settlement" | "statement";
  query: ReportQuery;
  onClose(): void;
}) {
  const [format, setFormat] = useState<"print" | "pdf" | "xlsx">("pdf");
  const online = useConnection((s) => s.status === "online");
  const save = useMutation({ mutationFn: () => finora.hr.export(tab, format, query), onSuccess: onClose });
  return (
    <SupplierModal title="طباعة وتصدير التقرير" busy={save.isPending} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <p className="rounded-control bg-violet-soft p-3 text-xs leading-6 text-ink-soft">
          {tab === "settlement" ? (
            "كشف نهاية الخدمة يُطبع من النسخة المحفوظة وقت إنهاء الخدمة. المبالغ تحتاج اعتماداً وصرفاً منفصلين من الخزينة."
          ) : tab === "statement" ? (
            "الكشف يجمع القيود والدفعات ضمن الفترة، مع رصيد أول الفترة. السلف تُعرض بذمة مستقلة وبالرصيد الحالي وقت التصدير."
          ) : (
            <>
              يشمل التقرير كل السجلات المطابقة للفلاتر والفترة المحددة، ضمن نطاق صلاحياتك. الرواتب تُعرض من
              نسخة المسير المحفوظة.
            </>
          )}
        </p>
        <label className="block space-y-2 text-xs">
          الصيغة
          <select
            className={hrInput}
            value={format}
            onChange={(e) => setFormat(e.target.value as typeof format)}
          >
            <option value="pdf">ملف PDF</option>
            <option value="xlsx">ملف Excel</option>
            <option value="print">معاينة وطباعة</option>
          </select>
        </label>
        {!online && <p className="text-xs text-danger">تصدير التقرير الكامل يحتاج اتصالاً بالسيرفر.</p>}
        {save.error && (
          <p role="alert" className="text-xs text-danger">
            {toFinoraError(save.error).message}
          </p>
        )}
        <button className={hrPrimary} disabled={!online || save.isPending}>
          {save.isPending ? "تجهيز التقرير…" : "تجهيز التقرير"}
        </button>
      </form>
    </SupplierModal>
  );
}
