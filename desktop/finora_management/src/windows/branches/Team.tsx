import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus, Users, X } from "lucide-react";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { BranchPerson } from "@/api/finora/branches";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { supplierSecondary } from "../suppliers/SupplierDialogs";
import { Panel } from "../shipping/shared";

/** Staff of one branch: home employees and those assigned as extra; admin-only assignment. */
export function BranchTeam({
  branchId,
  canManage,
  active,
}: {
  branchId: number;
  canManage: boolean;
  active: boolean;
}) {
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [pick, setPick] = useState("");
  const [mode, setMode] = useState<"extra" | "move">("extra");

  const people = useQuery({
    queryKey: ["branches", "people"],
    queryFn: () => finora.branches.people(),
    enabled: active && canManage,
  });
  const done = async (message: string) => {
    toast.success(message);
    setAdding(false);
    setPick("");
    await client.invalidateQueries({ queryKey: ["branches"] });
  };
  const assign = useMutation({
    mutationFn: () => finora.branches.assignPerson(Number(pick), { branch_id: branchId, mode }),
    onSuccess: () =>
      done(mode === "move" ? "نُقل الموظف — السجلات السابقة بقيت بفروعها" : "أُضيف الموظف للفرع"),
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const unassign = useMutation({
    mutationFn: (employeeId: number) => finora.branches.unassignPerson(employeeId, branchId),
    onSuccess: () => done("أُزيل تعيين الموظف من الفرع"),
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  if (!canManage) return null;
  const all = people.data?.rows ?? [];
  const team = all.filter(
    (p) => p.home_branch_id === branchId || p.extras.some((x) => x.branch_id === branchId),
  );
  const candidates = all.filter((p) => !team.includes(p));
  const label = (p: BranchPerson) => (p.home_branch_id === branchId ? "أساسي" : "إضافي");

  return (
    <Panel title="موظفو الفرع" icon={Users} className="shrink-0">
      <ul className="space-y-1.5 text-[13px]">
        {team.length === 0 && <li className="text-muted">لا موظفين معيّنين</li>}
        {team.map((p) => (
          <li key={p.id} className="flex items-center justify-between gap-2">
            <span>
              {p.name} <span className="text-[11px] text-muted">({label(p)})</span>
            </span>
            {p.home_branch_id !== branchId && (
              <button
                type="button"
                aria-label={`إزالة ${p.name} من الفرع`}
                disabled={!online || unassign.isPending}
                onClick={() => unassign.mutate(p.id)}
              >
                <X size={14} />
              </button>
            )}
          </li>
        ))}
      </ul>
      {adding ? (
        <div className="mt-3 space-y-2">
          <select
            aria-label="الموظف"
            className="w-full rounded-lg border px-2 py-1.5"
            value={pick}
            onChange={(e) => setPick(e.target.value)}
          >
            <option value="">اختر موظفاً…</option>
            {candidates.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.home_branch || "بلا فرع"}
              </option>
            ))}
          </select>
          <select
            aria-label="نوع التعيين"
            className="w-full rounded-lg border px-2 py-1.5"
            value={mode}
            onChange={(e) => setMode(e.target.value as "extra" | "move")}
          >
            <option value="extra">يعمل أيضاً في هذا الفرع</option>
            <option value="move">نقله إلى هذا الفرع (أساسي)</option>
          </select>
          <div className="flex gap-2">
            <button
              type="button"
              className={supplierSecondary}
              disabled={!pick || !online || assign.isPending}
              onClick={() => assign.mutate()}
            >
              حفظ
            </button>
            <button type="button" className={supplierSecondary} onClick={() => setAdding(false)}>
              إلغاء
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className={`${supplierSecondary} mt-3`}
          disabled={!online}
          onClick={() => setAdding(true)}
        >
          <UserPlus size={15} /> تعيين موظف
        </button>
      )}
    </Panel>
  );
}
