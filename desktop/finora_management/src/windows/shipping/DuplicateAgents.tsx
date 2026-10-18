import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { ConfirmDialog } from "@/components/Dialog";
import { toast } from "@/stores/toasts";
import { supplierSecondary } from "../suppliers/SupplierDialogs";

type Group = Awaited<ReturnType<typeof finora.shipping.duplicateAgents>>["rows"][number];

/** Real merge of same-branch duplicate agent records. Shown to the general admin only (others get 403 → hidden). */
export function DuplicateAgents({ enabled }: { enabled: boolean }) {
  const client = useQueryClient();
  const [pending, setPending] = useState<Group | null>(null);
  const dups = useQuery({
    queryKey: ["shipping", "agents", "duplicates"],
    queryFn: () => finora.shipping.duplicateAgents(),
    enabled,
    retry: false,
  });
  const merge = useMutation({
    mutationFn: (g: Group) =>
      finora.shipping.mergeAgents(
        g.primary_id,
        g.duplicates.map((d) => d.id),
      ),
    onSuccess: async (res) => {
      setPending(null);
      toast.success(`تم الدمج — نُقل ${res.invoices_moved} طلب إلى السجل الأساسي`);
      await client.invalidateQueries({ queryKey: ["shipping"] });
    },
    onError: (e: unknown) => {
      setPending(null);
      toast.error(toFinoraError(e).message);
    },
  });
  const rows = dups.data?.rows ?? [];
  if (rows.length === 0) return null;
  return (
    <section
      aria-label="مناديب مكررون"
      className="mb-3 rounded-panel bg-amber-50 p-3 text-[13px] ring-1 ring-amber-200"
    >
      <p className="mb-2 font-semibold">سجلات مندوبين مكررة داخل نفس الفرع</p>
      <ul className="space-y-2">
        {rows.map((g) => (
          <li
            key={`${g.branch_id}-${g.primary_id}`}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <span>
              {g.name} — {g.duplicates.length} نسخة مكررة
              {g.duplicates.some((d) => d.blocker) && (
                <span className="text-danger"> · {g.duplicates.find((d) => d.blocker)?.blocker}</span>
              )}
            </span>
            <button
              type="button"
              className={supplierSecondary}
              disabled={!g.can_merge}
              onClick={() => setPending(g)}
            >
              دمج
            </button>
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={pending !== null}
        title="دمج مناديب مكررين"
        busy={merge.isPending}
        message="ستُنقل طلبات النسخ المكررة وسجل مواقعها إلى السجل الأساسي وتُعطَّل النسخ المكررة (لا شيء يُحذف). تُؤخذ نسخة من قاعدة البيانات قبل الدمج حيث يمكن."
        confirmLabel="دمج"
        onClose={() => setPending(null)}
        onConfirm={() => pending && merge.mutate(pending)}
      />
    </section>
  );
}
