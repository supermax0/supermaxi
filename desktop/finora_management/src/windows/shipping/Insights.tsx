import { useQuery } from "@tanstack/react-query";
import { AlarmClock, ListPlus, Loader2, SearchCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { SupplierModal, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";
import { Money, Panel, money, type Section } from "./shared";

const DAY_OPTIONS = [3, 7, 14, 30];

/** «طلبات لدى الجهة ولم ترد بالكشف» — refreshed whenever the manifest's rows change. */
export function MissingButton({
  manifestId,
  rowsCount,
  onOpen,
}: {
  manifestId: number;
  rowsCount: number;
  onOpen(): void;
}) {
  const missing = useQuery({
    queryKey: ["shipping", "manifest", manifestId, "missing", rowsCount],
    queryFn: () => finora.shipping.missing(manifestId),
  });
  const total = missing.data?.total ?? 0;
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!missing.data || total === 0}
      className={cn(
        "flex w-full items-center gap-2 rounded-control px-3 py-2.5 text-start text-[12px] transition-colors",
        total > 0 ? "bg-warning-soft text-warning hover:brightness-95" : "bg-surface-sunken text-ink-faint",
      )}
    >
      <SearchCheck size={16} className="shrink-0" />
      <span className="flex-1">
        {missing.isPending
          ? "فحص الطلبات الناقصة…"
          : total > 0
            ? `${formatNumber(total)} طلب لدى الجهة لم يرد في الكشف (${money(missing.data?.amount ?? 0)})`
            : "لا توجد طلبات ناقصة لدى الجهة"}
      </span>
    </button>
  );
}

export function MissingOrdersDialog({
  manifestId,
  busy,
  onAdd,
  onClose,
}: {
  manifestId: number;
  busy: boolean;
  onAdd(ids: number[]): void;
  onClose(): void;
}) {
  const missing = useQuery({
    queryKey: ["shipping", "manifest", manifestId, "missing", "dialog"],
    queryFn: () => finora.shipping.missing(manifestId),
  });
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const rows = useMemo(() => missing.data?.rows ?? [], [missing.data]);
  const free = rows.filter((r) => !r.in_manifest);
  const toggle = (id: number) =>
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <SupplierModal
      title="طلبات لدى الجهة ولم ترد في الكشف"
      icon={SearchCheck}
      busy={busy}
      onClose={onClose}
      wide
    >
      <p className="mb-3 text-[12px] leading-5 text-ink-soft">
        طلبات مشحونة أو واصلة لهذه الجهة وما زال مبلغها مستحقاً، ولم تُدرج في هذا الكشف. الأقدم أولاً — راجعها
        مع الجهة: هل وصلت ولم تُذكر، أم ما زالت قيد التوصيل؟
      </p>
      {missing.isPending ? (
        <p className="py-10 text-center text-ink-faint">جارٍ الفحص…</p>
      ) : missing.error ? (
        <p className="py-10 text-center text-danger">{toFinoraError(missing.error).message}</p>
      ) : (
        <div className="max-h-[420px] overflow-y-auto rounded-control border border-line/70">
          <table className="w-full text-[13px]" aria-label="الطلبات الناقصة">
            <thead className="sticky top-0 bg-white text-[11px] text-ink-faint">
              <tr>
                <th className="w-10 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label="تحديد الكل"
                    checked={free.length > 0 && free.every((r) => picked.has(r.id))}
                    onChange={(e) => setPicked(e.target.checked ? new Set(free.map((r) => r.id)) : new Set())}
                  />
                </th>
                <th className="px-2 py-2 text-start font-medium">الطلب</th>
                <th className="px-2 py-2 text-start font-medium">العميل</th>
                <th className="px-2 py-2 text-start font-medium">المستحق</th>
                <th className="px-2 py-2 text-start font-medium">الحالة</th>
                <th className="px-2 py-2 text-start font-medium">مدة لدى الجهة</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {rows.map((r) => (
                <tr key={r.id} className={r.in_manifest ? "opacity-60" : ""}>
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`تحديد ${r.id}`}
                      disabled={!!r.in_manifest}
                      checked={picked.has(r.id)}
                      onChange={() => toggle(r.id)}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <span className="ltr-isolate font-bold">#{r.id}</span>
                    {r.in_manifest && (
                      <p className="text-[10px] text-ink-faint">
                        في الكشف <span className="ltr-isolate">{r.in_manifest}</span>
                      </p>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <p className="max-w-[180px] truncate">{r.customer_name || "—"}</p>
                    <p className="text-[11px] text-ink-faint">{r.customer_city}</p>
                  </td>
                  <td className="px-2 py-2 font-semibold">
                    <Money value={r.remaining} />
                  </td>
                  <td className="px-2 py-2 text-[12px] text-ink-soft">{r.status}</td>
                  <td className="px-2 py-2">
                    <DaysBadge days={r.days_out} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-4 flex items-center gap-2">
        <p className="flex-1 text-[12px] text-ink-soft">
          {missing.data &&
            missing.data.total > rows.length &&
            `تُعرض أقدم ${formatNumber(rows.length)} من ${formatNumber(missing.data.total)}`}
        </p>
        <button type="button" className={supplierSecondary} onClick={onClose}>
          إغلاق
        </button>
        <button
          type="button"
          className={supplierPrimary}
          disabled={picked.size === 0 || busy}
          onClick={() => onAdd([...picked])}
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <ListPlus size={16} />}
          إضافة {picked.size ? formatNumber(picked.size) : ""} للكشف
        </button>
      </div>
    </SupplierModal>
  );
}

function DaysBadge({ days }: { days: number }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[11px] font-semibold",
        days >= 14
          ? "bg-danger-soft text-danger"
          : days >= 7
            ? "bg-warning-soft text-warning"
            : "bg-surface-sunken text-ink-soft",
      )}
    >
      <span className="ltr-isolate">{formatNumber(days)}</span> يوم
    </span>
  );
}

type OverdueTab = "parcels" | "returns" | "manifests";

/** المتأخرات: parcels out too long, returns not received / inspected, settlement drafts left open. */
export function OverduePanel({
  enabled,
  onOpenManifest,
  onSection,
}: {
  enabled: boolean;
  onOpenManifest(id: number): void;
  onSection(section: Section): void;
}) {
  const [days, setDays] = useState(7);
  const [tab, setTab] = useState<OverdueTab>("parcels");
  const overdue = useQuery({
    queryKey: ["shipping", "overdue", days],
    queryFn: () => finora.shipping.overdue(days),
    enabled,
  });
  const data = overdue.data;
  const tabs: Array<{ id: OverdueTab; label: string }> = [
    { id: "parcels", label: "طلبات متأخرة" },
    { id: "returns", label: "مرتجعات معلقة" },
    { id: "manifests", label: "كشوف مفتوحة" },
  ];
  return (
    <Panel
      title="المتأخرات"
      icon={AlarmClock}
      className="overflow-hidden"
      actions={
        <select
          aria-label="مدة التأخير"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="h-8 rounded-[10px] border border-line bg-white px-2 text-[12px]"
        >
          {DAY_OPTIONS.map((d) => (
            <option key={d} value={d}>
              أكثر من {d} أيام
            </option>
          ))}
        </select>
      }
    >
      <div className="mb-2 flex gap-1" role="tablist" aria-label="أنواع المتأخرات">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium",
              tab === t.id ? "bg-maroon text-white" : "bg-surface-sunken text-ink-soft",
            )}
          >
            {t.label}
            <span className="ltr-isolate opacity-75">{formatNumber(data?.counts[t.id] ?? 0)}</span>
          </button>
        ))}
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-line/60 overflow-y-auto text-[13px]">
        {overdue.isPending && <li className="py-8 text-center text-ink-faint">جارٍ التحميل…</li>}
        {overdue.error && (
          <li className="py-8 text-center text-danger">{toFinoraError(overdue.error).message}</li>
        )}
        {data && data.counts[tab] === 0 && (
          <li className="py-8 text-center text-ink-faint">لا توجد متأخرات 🎉</li>
        )}
        {tab === "parcels" &&
          data?.parcels.map((p) => (
            <li key={p.id} className="flex items-center gap-2 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate">
                  <span className="ltr-isolate font-bold">#{p.id}</span> ·{" "}
                  {p.shipping_company || p.delivery_agent}
                </p>
                <p className="truncate text-[11px] text-ink-faint">
                  {p.customer_name} · <Money value={p.remaining} />
                </p>
              </div>
              <DaysBadge days={p.days_out} />
            </li>
          ))}
        {tab === "returns" &&
          data?.returns.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 py-2 text-start"
                onClick={() => onSection("returns")}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate">
                    <span className="ltr-isolate font-bold">#{r.order_id}</span> · {r.party_name}
                  </p>
                  <p className="text-[11px] text-ink-faint">
                    {r.state === "awaiting" ? "لم يُستلم بعد" : "مستلم ولم يُفحص"}
                  </p>
                </div>
                <DaysBadge days={r.days} />
              </button>
            </li>
          ))}
        {tab === "manifests" &&
          data?.manifests.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 py-2 text-start"
                onClick={() => onOpenManifest(m.id)}
              >
                <div className="min-w-0 flex-1">
                  <p className="ltr-isolate truncate text-right font-bold">{m.number}</p>
                  <p className="text-[11px] text-ink-faint">
                    {m.carrier || m.agent} · {formatNumber(m.orders_count)} طلب
                  </p>
                </div>
                <DaysBadge days={m.days} />
              </button>
            </li>
          ))}
      </ul>
      {tab === "parcels" && data && data.amount > 0 && (
        <p className="mt-2 border-t border-line/60 pt-2 text-[12px] text-ink-soft">
          قيمة الطلبات المتأخرة <Money value={data.amount} className="font-bold text-maroon" />
        </p>
      )}
    </Panel>
  );
}
