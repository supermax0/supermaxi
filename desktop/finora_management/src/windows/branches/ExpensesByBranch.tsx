import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { Metric, Money, Panel } from "../shipping/shared";
import { ExpenseKinds } from "./ExpenseKinds";

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Expenses per branch for a period. Shared/central attribution is configured server-side; the total never changes. */
export function ExpensesByBranch({ enabled }: { enabled: boolean }) {
  const defaults = useMemo(() => {
    const now = new Date();
    return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) };
  }, []);
  const [from, setFrom] = useState(defaults.from);
  const [to, setTo] = useState(defaults.to);
  const valid = Boolean(from) && Boolean(to) && from <= to;
  const report = useQuery({
    queryKey: ["branches", "expense-report", from, to],
    queryFn: () => finora.branches.expenseReport(from, to),
    enabled: enabled && valid,
  });
  const data = report.data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[12.5px] text-ink-soft">
          من
          <input
            type="date"
            aria-label="من تاريخ"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="ltr-isolate mt-1 block h-10 rounded-control border border-line bg-white px-3"
          />
        </label>
        <label className="text-[12.5px] text-ink-soft">
          إلى
          <input
            type="date"
            aria-label="إلى تاريخ"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="ltr-isolate mt-1 block h-10 rounded-control border border-line bg-white px-3"
          />
        </label>
      </div>
      {!valid && <p className="text-sm text-danger">حدد فترة صحيحة</p>}
      {report.error && <p className="text-sm text-danger">{toFinoraError(report.error).message}</p>}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Metric label="إجمالي مصاريف الشركة" value={<Money value={data.company_total} />} />
            <Metric label="إدارة رئيسية" value={<Money value={data.central} />} />
            <Metric label="غير مرتبط بفرع" value={<Money value={data.unassigned} />} />
            <Metric
              label="مجموع الفروع"
              value={<Money value={data.branches.reduce((a, b) => a + b.amount, 0)} />}
            />
          </div>
          <Panel title="مصاريف كل فرع (مباشر + حصة المشترك)">
            <ul className="space-y-1.5 text-[13.5px]">
              {data.branches.length === 0 && <li className="text-ink-faint">لا مصاريف بهذه الفترة</li>}
              {data.branches.map((b) => (
                <li key={b.branch_id} className="flex justify-between">
                  <span>{b.branch}</span>
                  <Money value={b.amount} />
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}
      <ExpenseKinds enabled={enabled && valid} from={from} to={to} />
    </div>
  );
}
