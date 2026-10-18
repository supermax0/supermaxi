import { useQuery } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import { useConnection } from "@/stores/connection";
import { useHRNavigation } from "@/stores/hrNavigation";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import { hrSecondary } from "./shared";
const approvalTypes = new Set(["leave", "advance", "correction", "payroll_review", "applicant"]);
export function ApprovalCenter({ onClose }: { onClose(): void }) {
  const online = useConnection((s) => s.status === "online");
  const data = useQuery({
    queryKey: ["hr", "approvals"],
    queryFn: finora.hr.notifications,
    enabled: online,
    refetchInterval: online ? 30000 : false,
  });
  const rows = (data.data?.items ?? []).filter((r) => approvalTypes.has(r.type));
  return (
    <SupplierModal title="مركز الموافقات" busy={false} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-xs leading-6 text-ink-soft">
          الطلبات المعروضة ضمن صلاحياتك. افتح المراجعة لعرض التفاصيل واتخاذ القرار من تبويب الطلب.
        </p>
        {!online && <p className="text-xs text-danger">المراجعة والاعتماد يحتاجان اتصالاً بالسيرفر.</p>}
        {data.error && (
          <p role="alert" className="text-xs text-danger">
            {toFinoraError(data.error).message}
          </p>
        )}
        {online && data.isLoading && <p className="text-xs text-ink-faint">تحميل الطلبات…</p>}
        {rows.map((r) => (
          <section key={r.key} className="rounded-control border border-line/70 p-3">
            <strong className="text-xs">{r.title}</strong>
            <p className="mt-2 text-xs text-ink-soft">{r.body}</p>
            <button
              className={`${hrSecondary} mt-3`}
              disabled={!online}
              onClick={() => {
                useHRNavigation.getState().set(r);
                onClose();
              }}
            >
              مراجعة الطلب
            </button>
          </section>
        ))}
        {online && !data.isLoading && !rows.length && !data.error && (
          <p className="p-4 text-center text-xs text-ink-faint">لا توجد موافقات معلقة ضمن صلاحياتك</p>
        )}
        {!!rows.length && (
          <p className="text-xs text-ink-faint">
            تظهر أحدث الطلبات من كل نوع. تبويب الطلب يعرض القائمة الكاملة.
          </p>
        )}
      </div>
    </SupplierModal>
  );
}
