import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import { useConnection } from "@/stores/connection";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import type { HRAction } from "./HRDialogs";
import { HRBadge, hrLocalDateTime, hrSecondary } from "./shared";

export function AttendanceRequests({
  onClose,
  onAction,
  canApprove,
}: {
  onClose(): void;
  onAction(action: HRAction): void;
  canApprove: boolean;
}) {
  const [page, setPage] = useState(1);
  const online = useConnection((s) => s.status === "online");
  const data = useQuery({
    queryKey: ["hr", "corrections", page],
    queryFn: () => finora.hr.corrections(page),
    enabled: online,
  });
  return (
    <SupplierModal title="طلبات تصحيح الحضور" busy={false} onClose={onClose}>
      <div className="max-h-[60vh] space-y-3 overflow-auto">
        {!online && (
          <p className="text-xs text-ink-soft">
            مراجعة الطلبات تحتاج اتصالاً بالسيرفر. الطلب المحلي يبقى محفوظاً ضمن المزامنة.
          </p>
        )}
        {data.isLoading && online && <p>تحميل الطلبات…</p>}
        {data.error && (
          <p role="alert" className="text-xs text-danger">
            {toFinoraError(data.error).message}
          </p>
        )}
        {data.data?.rows.map((row) => (
          <section key={row.id} className="rounded-panel border border-line p-4 text-xs">
            <div className="flex items-center justify-between gap-2">
              <strong>
                {row.person_name} · {row.code}
              </strong>
              <HRBadge state={row.status} />
            </div>
            <p className="mt-3 text-ink-soft">
              الحضور المطلوب: {hrLocalDateTime(row.detail.check_in).replace("T", " ")} · الانصراف:{" "}
              {hrLocalDateTime(row.detail.check_out).replace("T", " ") || "—"}
            </p>
            <p className="mt-2 whitespace-pre-wrap">{row.detail.reason}</p>
            {row.decision && <p className="mt-2 text-ink-soft">قرار المراجعة: {row.decision}</p>}
            {canApprove && row.status === "pending" && (
              <div className="mt-3 flex gap-2">
                {["approved", "rejected"].map((status) => (
                  <button
                    key={status}
                    className={hrSecondary}
                    disabled={!online}
                    onClick={() =>
                      onAction({
                        title: status === "approved" ? "اعتماد تصحيح الحضور" : "رفض تصحيح الحضور",
                        action: "attendance.correction_decide",
                        payload: { correction_id: row.id, version: row.version, status },
                        fields: [{ name: "reason", label: "سبب القرار", required: true }],
                      })
                    }
                  >
                    {status === "approved" ? "اعتماد" : "رفض"}
                  </button>
                ))}
              </div>
            )}
          </section>
        ))}
        {online && !data.isLoading && data.data?.rows.length === 0 && (
          <p className="py-6 text-center text-ink-faint">لا توجد طلبات تصحيح</p>
        )}
      </div>
      <div className="mt-3 flex items-center justify-between text-xs">
        <button className={hrSecondary} disabled={page <= 1} onClick={() => setPage(page - 1)}>
          السابق
        </button>
        <span>
          {page} / {data.data?.total_pages ?? 1} · {data.data?.total ?? 0} طلب
        </span>
        <button
          className={hrSecondary}
          disabled={page >= (data.data?.total_pages ?? 1)}
          onClick={() => setPage(page + 1)}
        >
          التالي
        </button>
      </div>
    </SupplierModal>
  );
}
