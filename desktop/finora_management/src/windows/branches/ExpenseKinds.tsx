import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { ExpenseRow } from "@/api/finora/expenses";
import { toast } from "@/stores/toasts";
import { Money, Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

const RULES: Record<string, string> = {
  fixed: "نسبة ثابتة",
  sales: "نسبة المبيعات",
  employees: "عدد الموظفين",
  area: "المساحة (أوزان)",
  manual: "يدوي (مبالغ)",
};
const KIND_LABEL = { branch: "خاص بفرع", central: "إدارة رئيسية", shared: "مشترك" } as const;
type Kind = keyof typeof KIND_LABEL;

/** Classifies period expenses as branch / central / shared. A reporting overlay: the expense itself is untouched. */
export function ExpenseKinds({ enabled, from, to }: { enabled: boolean; from: string; to: string }) {
  const [editing, setEditing] = useState<ExpenseRow | null>(null);
  const list = useQuery({
    queryKey: ["branches", "expense-list", from, to],
    queryFn: () =>
      finora.expenses.list({
        tab: "all",
        search: "",
        category: "",
        treasuryAccountId: null,
        dateFrom: from,
        dateTo: to,
        sort: "date",
        page: 1,
        pageSize: 50,
      }),
    enabled,
  });
  const assigned = useQuery({
    queryKey: ["branches", "expense-assignments", from, to],
    queryFn: () => finora.branches.expenseAssignments(from, to),
    enabled,
  });
  const rows = list.data?.rows ?? []; // payroll rows included: salaries can be loaded on a branch or shared too
  return (
    <Panel title="تصنيف المصاريف (خاص بفرع / إدارة رئيسية / مشترك)">
      <ul className="space-y-1.5 text-[13px]">
        {rows.length === 0 && <li className="text-ink-faint">لا مصاريف بهذه الفترة</li>}
        {rows.map((r) => {
          const kind: Kind = assigned.data?.rows[String(r.id)]?.kind ?? "branch";
          return (
            <li key={r.id} className="flex items-center justify-between gap-2">
              <span>
                {r.title} · <Money value={r.amount} />
              </span>
              <button type="button" className={supplierSecondary} onClick={() => setEditing(r)}>
                {KIND_LABEL[kind]}
              </button>
            </li>
          );
        })}
      </ul>
      {editing && <Editor expense={editing} from={from} to={to} onClose={() => setEditing(null)} />}
    </Panel>
  );
}

function Editor({
  expense,
  from,
  to,
  onClose,
}: {
  expense: ExpenseRow;
  from: string;
  to: string;
  onClose(): void;
}) {
  const client = useQueryClient();
  const [kind, setKind] = useState<Kind>("branch");
  const [rule, setRule] = useState("fixed");
  const [weights, setWeights] = useState<Record<string, string>>({});
  const meta = useQuery({ queryKey: ["branches", "meta"], queryFn: () => finora.branches.meta() });
  const branches = meta.data?.scope.branches ?? [];
  const numeric: Record<string, number> = {};
  for (const [id, value] of Object.entries(weights)) if (Number(value) > 0) numeric[id] = Number(value);
  const chosen =
    rule === "sales" || rule === "employees" ? branches.map((b) => b.id) : Object.keys(numeric).map(Number);
  const preview = useMutation({
    mutationFn: () =>
      finora.branches.previewExpenseSplit({
        amount: expense.amount,
        rule,
        branch_ids: chosen,
        weights: numeric,
        from,
        to,
      }),
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const save = useMutation({
    mutationFn: () =>
      finora.branches.allocateExpense(expense.id, {
        kind,
        rule: kind === "shared" ? rule : undefined,
        branch_ids: kind === "shared" ? chosen : undefined,
        weights: numeric,
        from,
        to,
      }),
    onSuccess: async () => {
      toast.success("حُفظ التصنيف — المصروف نفسه لم يتغير");
      await client.invalidateQueries({ queryKey: ["branches"] });
      onClose();
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const usesWeights = rule === "fixed" || rule === "area" || rule === "manual";
  return (
    <div
      role="dialog"
      aria-label={`تصنيف ${expense.title}`}
      className="mt-3 space-y-3 rounded-panel bg-white/90 p-3 ring-1 ring-line/60"
    >
      <p className="font-semibold">
        {expense.title} — <Money value={expense.amount} />
      </p>
      <select
        aria-label="نوع المصروف"
        className={supplierInput}
        value={kind}
        onChange={(e) => setKind(e.target.value as Kind)}
      >
        {Object.entries(KIND_LABEL).map(([k, l]) => (
          <option key={k} value={k}>
            {l}
          </option>
        ))}
      </select>
      {kind === "shared" && (
        <>
          <select
            aria-label="قاعدة التوزيع"
            className={supplierInput}
            value={rule}
            onChange={(e) => {
              setRule(e.target.value);
              preview.reset();
            }}
          >
            {Object.entries(RULES).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          {usesWeights && (
            <div className="grid gap-2 md:grid-cols-2">
              {branches.map((b) => (
                <label key={b.id} className="flex items-center justify-between gap-2 text-[13px]">
                  {b.name}
                  <input
                    aria-label={`وزن ${b.name}`}
                    className="h-9 w-28 rounded-control border border-line px-2"
                    inputMode="decimal"
                    value={weights[b.id] ?? ""}
                    onChange={(e) => setWeights({ ...weights, [b.id]: e.target.value })}
                  />
                </label>
              ))}
            </div>
          )}
          <button
            type="button"
            className={supplierSecondary}
            disabled={preview.isPending}
            onClick={() => preview.mutate()}
          >
            معاينة التوزيع
          </button>
          {preview.data && (
            <ul className="text-[13px]">
              {preview.data.lines.map((l) => (
                <li key={l.branch_id} className="flex justify-between">
                  <span>{l.branch}</span>
                  <Money value={l.amount} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          className={supplierPrimary}
          disabled={save.isPending || (kind === "shared" && !preview.data)}
          onClick={() => save.mutate()}
        >
          حفظ
        </button>
        <button type="button" className={supplierSecondary} onClick={onClose}>
          إلغاء
        </button>
      </div>
    </div>
  );
}
