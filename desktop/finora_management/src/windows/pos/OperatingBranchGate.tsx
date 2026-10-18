import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Loader2 } from "lucide-react";
import { finora, toFinoraError } from "@/api/finora";
import { toast } from "@/stores/toasts";

/**
 * «All branches» is a view scope: a sale must name ONE operating branch. When the POS opens without one
 * (general admin viewing every branch of a multi-branch company) this asks for it, switches the server
 * session to that branch and reloads the catalogue, stock and accounts for it. The server refuses a sale
 * without a branch anyway — this only makes the reason obvious before the cashier fills a cart.
 */
export function OperatingBranchGate({ branchId }: { branchId: number | null | undefined }) {
  const client = useQueryClient();
  const meta = useQuery({
    queryKey: ["branches", "meta"],
    queryFn: () => finora.branches.meta(),
    enabled: branchId === null,
    staleTime: 30_000,
  });
  const change = useMutation({
    mutationFn: (id: number) => finora.branches.switchScope({ branch_id: id }),
    onSuccess: async () => {
      await client.invalidateQueries();
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const scope = meta.data?.scope;
  if (branchId !== null || !meta.data || !scope || scope.branches.length < 2) return null;
  return (
    <section
      role="alert"
      aria-label="اختيار فرع البيع"
      className="rounded-panel border border-warning/30 bg-warning-soft/70 p-4"
    >
      <p className="text-sm font-bold text-ink">اختر فرع البيع قبل البدء</p>
      <p className="mt-1 text-[12px] leading-5 text-ink-soft">
        أنت تعرض «جميع الفروع»، والبيع يُسجَّل على فرع واحد محدد (مخزونه وصندوقه). اختر الفرع الذي تبيع منه.
      </p>
      {scope.can_switch ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {scope.branches.map((b) => (
            <button
              key={b.id}
              type="button"
              disabled={change.isPending}
              onClick={() => change.mutate(b.id)}
              className="inline-flex h-10 items-center gap-2 rounded-control border border-line bg-white px-4 text-sm font-semibold text-ink shadow-control hover:bg-violet-soft disabled:opacity-50"
            >
              {change.isPending && change.variables === b.id ? (
                <Loader2 size={15} className="animate-spin" />
              ) : (
                <Building2 size={15} className="text-maroon" />
              )}
              {b.name}
            </button>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-[12px] text-danger">لا تملك صلاحية تبديل الفرع؛ راجع المدير.</p>
      )}
    </section>
  );
}
