import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import { useConnection } from "@/stores/connection";
import { formatIqd } from "@/utils/money";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import { HRReportDialog } from "./HRReportDialog";
import { hrInput, hrSecondary, hrLocalDateTime } from "./shared";
type Document = Awaited<ReturnType<typeof finora.hr.statement>>["rows"][number]["document"];

export function FinancialStatement({
  personId,
  canExport,
  onClose,
}: {
  personId: number;
  canExport: boolean;
  onClose(): void;
}) {
  const online = useConnection((s) => s.status === "online");
  const [page, setPage] = useState(1);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [report, setReport] = useState(false);
  const [document, setDocument] = useState<Document | null>(null);
  const query = {
    person_id: personId,
    ...(from ? { date_from: from } : {}),
    ...(to ? { date_to: to } : {}),
    page,
  };
  const data = useQuery({
    queryKey: ["hr", "statement", query],
    queryFn: () => finora.hr.statement(query),
    enabled: online,
  });
  return (
    <SupplierModal title="كشف الحساب المالي للموظف" busy={false} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-soft">
            من
            <input
              type="date"
              className={hrInput}
              value={from}
              onChange={(e) => {
                setFrom(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="text-xs text-ink-soft">
            إلى
            <input
              type="date"
              className={hrInput}
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                setPage(1);
              }}
            />
          </label>
          {canExport && (
            <button className={hrSecondary} disabled={!online} onClick={() => setReport(true)}>
              طباعة وتصدير الكشف
            </button>
          )}
        </div>
        {!online && (
          <p className="text-xs text-ink-soft">
            الكشف المالي الكامل يحتاج اتصالاً بالسيرفر. يمكنك مراجعة الرواتب والسلف المخزنة من ملف الموظف.
          </p>
        )}
        {data.error && (
          <p role="alert" className="text-xs text-danger">
            {toFinoraError(data.error).message}
          </p>
        )}
        {data.isLoading && online && <p className="text-xs text-ink-faint">تحميل الكشف…</p>}
        {data.data && (
          <>
            <p className="text-sm font-semibold">
              {data.data.name} · {data.data.code}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <p className="rounded-control bg-violet-soft p-3 text-xs">
                مستحقات الموظف{" "}
                <strong className="mt-2 block text-lg text-violet">{formatIqd(data.data.balance)}</strong>
              </p>
              <p className="rounded-control bg-maroon-soft p-3 text-xs">
                ذمم السلف الحالية{" "}
                <strong className="mt-2 block text-lg text-maroon">
                  {formatIqd(data.data.advance_remaining)}
                </strong>
              </p>
            </div>
            <p className="text-xs text-ink-faint">
              رصيد أول الفترة: {formatIqd(data.data.opening)} · الاستقطاعات والتسويات لا تُحسب كدفعات نقدية.
            </p>
            <div className="max-h-72 overflow-auto rounded-control border border-line/70">
              <table className="w-full min-w-[700px] text-xs" aria-label="كشف مستحقات الموظف">
                <thead className="sticky top-0 bg-violet-soft">
                  <tr>
                    {["التاريخ", "العملية", "المستحق", "المدفوع", "التسويات", "الرصيد", "المستند"].map(
                      (h) => (
                        <th key={h} className="p-3 text-start font-medium">
                          {h}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {data.data.rows.map((r) => (
                    <tr key={r.key} className="border-t border-line/60">
                      <td className="p-3 whitespace-nowrap">{hrLocalDateTime(r.date).replace("T", " ")}</td>
                      <td className="p-3">{r.label}</td>
                      {[r.due, r.paid, r.adjustment, r.balance].map((n, i) => (
                        <td key={i} className="p-3 whitespace-nowrap">
                          {formatIqd(n)}
                        </td>
                      ))}
                      <td className="p-3">
                        <button className="text-violet underline" onClick={() => setDocument(r.document)}>
                          {r.document.number}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!data.data.rows.length && (
                <p className="p-6 text-center text-xs text-ink-faint">لا توجد قيود مالية بهذه الفترة</p>
              )}
            </div>
            <div className="flex items-center justify-between text-xs">
              <button
                className={hrSecondary}
                disabled={page <= 1 || data.isFetching}
                onClick={() => setPage(page - 1)}
              >
                السابق
              </button>
              <span>
                {page} من {data.data.total_pages} · {data.data.total} عملية
              </span>
              <button
                className={hrSecondary}
                disabled={page >= data.data.total_pages || data.isFetching}
                onClick={() => setPage(page + 1)}
              >
                التالي
              </button>
            </div>
            {data.data.advances.length > 0 && (
              <section className="rounded-control border border-line/70 p-3">
                <h3 className="text-xs font-semibold">السلف بذمة مستقلة</h3>
                {data.data.advances.map((r) => (
                  <p key={r.id} className="mt-3 flex justify-between gap-3 text-xs">
                    <span>
                      سلفة #{r.id} · {r.reason}
                    </span>
                    <span>المتبقي {formatIqd(r.remaining)}</span>
                  </p>
                ))}
              </section>
            )}
          </>
        )}
      </div>
      {report && (
        <HRReportDialog
          tab="statement"
          query={{
            period: "custom",
            person_id: personId,
            ...(from ? { date_from: from } : {}),
            ...(to ? { date_to: to } : {}),
          }}
          onClose={() => setReport(false)}
        />
      )}
      {document && (
        <SupplierModal title="المستند المحاسبي" busy={false} onClose={() => setDocument(null)}>
          <div className="space-y-3 text-sm">
            <strong>{document.number}</strong>
            <p>{document.description}</p>
            <p>مدين: {document.debit}</p>
            <p>دائن: {document.credit}</p>
            <p>{formatIqd(document.amount)}</p>
            <p className="text-xs text-ink-faint">
              المرجع #{document.reference_id} · المستند #{document.id}
            </p>
          </div>
        </SupplierModal>
      )}
    </SupplierModal>
  );
}
