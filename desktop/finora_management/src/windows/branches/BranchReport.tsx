import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { formatNumber } from "@/utils/format";
import { Money, Panel } from "../shipping/shared";

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Branch comparison for a period. Balances (stock, cash) are as of now; profit is not shown — no sourced figure. */
export function BranchReport({ enabled }: { enabled: boolean }) {
  const defaults = useMemo(() => {
    const now = new Date();
    return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) };
  }, []);
  const [from, setFrom] = useState(defaults.from);
  const [to, setTo] = useState(defaults.to);
  const valid = Boolean(from) && Boolean(to) && from <= to;
  const report = useQuery({
    queryKey: ["branches", "report", from, to],
    queryFn: () => finora.branches.report(from, to),
    enabled: enabled && valid,
  });
  const data = report.data;
  const money = (v: number | null | undefined) =>
    v === null || v === undefined ? "غير متاح" : <Money value={v} />;
  const columns: {
    label: string;
    cell: (r: NonNullable<typeof data>["branches"][number]) => React.ReactNode;
  }[] = [
    { label: "المبيعات", cell: (r) => money(r.sales) },
    { label: "الطلبات", cell: (r) => formatNumber(r.orders) },
    { label: "متوسط الفاتورة", cell: (r) => money(r.average_invoice) },
    { label: "الملغاة", cell: (r) => formatNumber(r.canceled) },
    { label: "المرتجعة", cell: (r) => formatNumber(r.returned) },
    { label: "قيمة المرتجع", cell: (r) => money(r.returns_value) },
    { label: "المصاريف", cell: (r) => money(r.expenses) },
    { label: "المخزون", cell: (r) => money(r.stock_value) },
    { label: "بالطريق", cell: (r) => money(r.in_transit_value) },
    { label: "الصندوق", cell: (r) => money(r.cash) },
  ];
  const totalKeys = [
    "sales",
    "orders",
    null,
    "canceled",
    "returned",
    "returns_value",
    "expenses",
    "stock_value",
    "in_transit_value",
    "cash",
  ] as const;
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
        <Panel title="المبيعات والمصاريف حسب الفرع">
          <Bars
            rows={data.branches.map((r) => ({ label: r.branch, sales: r.sales, expenses: r.expenses }))}
          />
        </Panel>
      )}
      {data && (
        <Panel title="مقارنة الفروع">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-[13px]">
              <thead>
                <tr className="text-start text-ink-soft">
                  <th className="p-2 text-start">الفرع</th>
                  {columns.map((c) => (
                    <th key={c.label} className="p-2 text-start">
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.branches.map((r) => (
                  <tr key={r.branch_id} className="border-t border-line/60">
                    <th className="p-2 text-start font-semibold">{r.branch}</th>
                    {columns.map((c) => (
                      <td key={c.label} className="ltr-isolate p-2">
                        {c.cell(r)}
                      </td>
                    ))}
                  </tr>
                ))}
                <tr className="border-t-2 border-line font-bold">
                  <th className="p-2 text-start">الإجمالي</th>
                  {totalKeys.map((k, i) => (
                    <td key={columns[i]?.label} className="ltr-isolate p-2">
                      {k === null
                        ? "—"
                        : k === "orders" || k === "canceled" || k === "returned"
                          ? formatNumber(data.totals[k] ?? 0)
                          : money(data.totals[k])}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[12.5px] text-ink-soft">
            إدارة رئيسية (خارج الفروع): <Money value={data.central_expenses} /> · مصاريف غير مرتبطة بفرع:{" "}
            <Money value={data.unassigned_expenses} />
          </p>
          <ul className="mt-2 list-disc ps-5 text-[12px] text-ink-faint">
            {data.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

/** Two horizontal bars per branch on one shared scale; the table below carries the exact numbers. */
function Bars({ rows }: { rows: { label: string; sales: number; expenses: number }[] }) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.sales, r.expenses]));
  return (
    <div role="img" aria-label="مخطط أعمدة: المبيعات والمصاريف لكل فرع" className="space-y-3">
      <div className="flex gap-4 text-[12px] text-ink-soft">
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm bg-azure" /> المبيعات
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm bg-danger" /> المصاريف
        </span>
      </div>
      {rows.map((r) => (
        <div key={r.label} className="text-[12.5px]">
          <div className="mb-1 font-semibold">{r.label}</div>
          <div
            className="h-2.5 rounded-sm bg-azure"
            style={{ width: `${(r.sales / max) * 100}%`, minWidth: r.sales ? 2 : 0 }}
          />
          <div
            className="mt-1 h-2.5 rounded-sm bg-danger"
            style={{ width: `${(r.expenses / max) * 100}%`, minWidth: r.expenses ? 2 : 0 }}
          />
        </div>
      ))}
    </div>
  );
}
