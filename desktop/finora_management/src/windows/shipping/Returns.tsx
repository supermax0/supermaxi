import { useTimeFormat } from "@/stores/displayTime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, Loader2, PackageOpen, ScanLine } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { ReturnState, ShippingReturn } from "@/api/finora/shipping";
import { DataTable, type Column } from "@/components/DataTable";
import { Field } from "@/components/FilterPanel";
import { SearchBox } from "@/components/SearchBox";
import { StatusTabs } from "@/components/StatusTabs";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { formatNumber, formatDateTime } from "@/utils/format";
import {
  SupplierModal,
  supplierInput,
  supplierPrimary,
  supplierSecondary,
} from "../suppliers/SupplierDialogs";
import { Money } from "./shared";

type Tab = "awaiting" | "received" | "closed";
const STATE_LABEL: Record<ReturnState, string> = {
  awaiting: "بانتظار الاستلام",
  received: "مستلم — بانتظار الفحص",
  closed: "مغلق",
};
const STATE_TONE: Record<ReturnState, string> = {
  awaiting: "bg-warning-soft text-warning",
  received: "bg-violet-soft text-violet-deep",
  closed: "bg-success-soft text-success",
};

/** طلب راجع ← بانتظار الاستلام ← تم استلام البضاعة ← فحص المنتج ← إغلاق المرتجع */
export function ReturnsSection({ enabled, canManage }: { enabled: boolean; canManage: boolean }) {
  useTimeFormat();
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const [tab, setTab] = useState<Tab>("awaiting");
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 250);
  const [scan, setScan] = useState("");
  const [inspecting, setInspecting] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["shipping", "returns", tab, search],
    queryFn: () => finora.shipping.returns(tab, search),
    enabled,
  });
  const receive = useMutation({
    mutationFn: (input: { code?: string; return_id?: number }) => finora.shipping.receiveReturn(input),
    onSuccess: async (res) => {
      toast.success(`استُلم مرتجع الطلب #${res.item.order_id}`);
      setScan("");
      await client.invalidateQueries({ queryKey: ["shipping", "returns"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const columns = useMemo<Column<ShippingReturn>[]>(
    () => [
      {
        id: "order",
        header: "الطلب",
        width: "16%",
        cell: (r) => (
          <div>
            <p className="ltr-isolate font-bold">#{r.order_id}</p>
            {r.waybills[0] && (
              <p className="ltr-isolate text-right text-[10px] text-ink-faint">{r.waybills[0]}</p>
            )}
          </div>
        ),
      },
      {
        id: "customer",
        header: "العميل",
        width: "20%",
        cell: (r) => (
          <div className="min-w-0">
            <p className="truncate font-medium">{r.customer_name || "—"}</p>
            <p className="text-[11px] text-ink-faint">{r.customer_city}</p>
          </div>
        ),
      },
      {
        id: "party",
        header: "الجهة / الكشف",
        width: "20%",
        cell: (r) => (
          <div className="min-w-0">
            <p className="truncate">{r.party_name}</p>
            <p className="ltr-isolate truncate text-right text-[10px] text-ink-faint">{r.manifest_number}</p>
          </div>
        ),
      },
      { id: "amount", header: "قيمة الطلب", width: "14%", cell: (r) => <Money value={r.order_amount} /> },
      {
        id: "dates",
        header: "التواريخ",
        width: "16%",
        minTableWidth: 820,
        cell: (r) => (
          <div className="ltr-isolate text-right text-[11px] text-ink-soft">
            <p>{r.reported_at}</p>
            {r.received_at && <p className="text-ink-faint">{r.received_at}</p>}
          </div>
        ),
      },
      {
        id: "state",
        header: "الحالة",
        width: "14%",
        cell: (r) => (
          <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-semibold", STATE_TONE[r.state])}>
            {STATE_LABEL[r.state]}
          </span>
        ),
      },
    ],
    [],
  );
  const actions = (r: ShippingReturn) =>
    !canManage ? null : r.state === "awaiting" ? (
      <button
        type="button"
        className={cn(supplierSecondary, "h-8 px-3 text-xs")}
        disabled={!online || receive.isPending}
        onClick={(e) => {
          e.stopPropagation();
          receive.mutate({ return_id: r.id });
        }}
      >
        استلام
      </button>
    ) : r.state === "received" ? (
      <button
        type="button"
        className={cn(supplierPrimary, "h-8 px-3 text-xs")}
        disabled={!online}
        onClick={(e) => {
          e.stopPropagation();
          setInspecting(r.id);
        }}
      >
        فحص وإغلاق
      </button>
    ) : null;

  const counts = list.data?.counts;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex shrink-0 flex-wrap items-center gap-2">
        <StatusTabs<Tab>
          label="مراحل المرتجع"
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "awaiting", label: "بانتظار الاستلام", count: counts?.awaiting },
            { id: "received", label: "بانتظار الفحص", count: counts?.received },
            { id: "closed", label: "مغلقة", count: counts?.closed },
          ]}
        />
        {canManage && (
          <form
            className="flex h-11 min-w-[260px] flex-1 items-center gap-2 rounded-control border border-line bg-white/85 px-3 shadow-control"
            onSubmit={(e) => {
              e.preventDefault();
              if (scan.trim()) receive.mutate({ code: scan.trim() });
            }}
          >
            <ScanLine size={18} className="text-maroon" />
            <input
              aria-label="استلام مرتجع بالباركود"
              value={scan}
              onChange={(e) => setScan(e.target.value)}
              placeholder="امسح باركود الطرد الراجع لتسجيل استلامه…"
              className="min-w-0 flex-1 bg-transparent text-[14px] outline-none"
            />
            {receive.isPending && <Loader2 size={16} className="animate-spin text-ink-faint" />}
          </form>
        )}
        <SearchBox
          value={searchText}
          onChange={setSearchText}
          busy={list.isFetching}
          placeholder="رقم الطلب أو الجهة…"
          className="w-[230px]"
        />
      </div>
      <DataTable
        label="المرتجعات"
        columns={columns}
        rows={list.data?.rows}
        loading={list.isPending}
        fetching={list.isFetching}
        error={list.error ? toFinoraError(list.error).message : null}
        onRetry={() => void list.refetch()}
        emptyTitle="لا توجد مرتجعات في هذه المرحلة"
        emptyHint="تُسجَّل الطلبات «راجع» هنا تلقائياً عند اعتماد كشف التسوية."
        rowActions={actions}
        onOpen={(r) => r.state !== "awaiting" && setInspecting(r.id)}
      />
      {inspecting != null && (
        <InspectionDialog id={inspecting} canManage={canManage} onClose={() => setInspecting(null)} />
      )}
    </div>
  );
}

function InspectionDialog({ id, canManage, onClose }: { id: number; canManage: boolean; onClose(): void }) {
  useTimeFormat();
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const details = useQuery({
    queryKey: ["shipping", "returns", "details", id],
    queryFn: () => finora.shipping.returnDetails(id),
  });
  const item = details.data?.item;
  const [branchId, setBranchId] = useState<number | null>(null);
  const [packagingOk, setPackagingOk] = useState(true);
  const [note, setNote] = useState("");
  const [damaged, setDamaged] = useState<Record<number, number>>({});
  useEffect(() => {
    if (item && branchId == null) setBranchId(item.branch_id ?? item.branches?.[0]?.id ?? null);
  }, [item, branchId]);
  const close = useMutation({
    mutationFn: () =>
      finora.shipping.closeReturn(id, {
        branch_id: branchId ?? 0,
        packaging_ok: packagingOk,
        note,
        lines: Object.entries(damaged)
          .filter(([, qty]) => qty > 0)
          .map(([itemId, qty]) => ({ item_id: Number(itemId), damaged: qty })),
      }),
    onSuccess: async (res) => {
      toast.success(
        res.item.writeoffs.length
          ? `أُغلق المرتجع وسُجل التالف بسند ${res.item.writeoffs.join("، ")}`
          : "أُغلق المرتجع وعادت البضاعة للمخزن",
      );
      await Promise.all([
        client.invalidateQueries({ queryKey: ["shipping"] }),
        client.invalidateQueries({ queryKey: ["orders"] }),
        client.invalidateQueries({ queryKey: ["products"] }),
      ]);
      onClose();
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const closed = item?.state === "closed";
  const anyDamaged = Object.values(damaged).some((q) => q > 0);
  return (
    <SupplierModal
      title={`فحص مرتجع الطلب #${item?.order_id ?? ""}`}
      icon={PackageOpen}
      busy={close.isPending}
      onClose={onClose}
      wide
    >
      {!item ? (
        <p className="py-10 text-center text-ink-faint">
          {details.error ? toFinoraError(details.error).message : "جارٍ التحميل…"}
        </p>
      ) : (
        <div className="grid gap-4">
          <p className="text-[13px] text-ink-soft">
            {item.customer_name} · {item.party_name} ·{" "}
            <span className="ltr-isolate">{item.manifest_number}</span>
          </p>
          <table className="w-full text-[13px]" aria-label="بنود المرتجع">
            <thead className="text-[11px] text-ink-faint">
              <tr>
                <th className="py-2 text-start font-medium">المنتج</th>
                <th className="py-2 text-start font-medium">الكمية المرتجعة</th>
                <th className="py-2 text-start font-medium">سليم يعود للبيع</th>
                <th className="py-2 text-start font-medium">تالف</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {(closed ? item.inspection : (item.items ?? [])).map((line) => {
                const lineId = line.item_id ?? 0;
                const qty = line.quantity ?? 0;
                const bad = closed ? ("damaged" in line ? (line.damaged ?? 0) : 0) : (damaged[lineId] ?? 0);
                return (
                  <tr key={lineId}>
                    <td className="py-2">
                      <p className="font-medium">{line.name}</p>
                      {line.variant && <p className="text-[11px] text-ink-faint">{line.variant}</p>}
                    </td>
                    <td className="ltr-isolate py-2 text-right">{formatNumber(qty)}</td>
                    <td className="ltr-isolate py-2 text-right font-semibold text-success">
                      {formatNumber(qty - bad)}
                    </td>
                    <td className="py-2">
                      {closed ? (
                        <span className="ltr-isolate font-semibold text-danger">{formatNumber(bad)}</span>
                      ) : (
                        <input
                          type="number"
                          min={0}
                          max={qty}
                          aria-label={`الكمية التالفة من ${line.name}`}
                          value={bad}
                          onChange={(e) =>
                            setDamaged((d) => ({
                              ...d,
                              [lineId]: Math.max(0, Math.min(qty, Number(e.target.value) || 0)),
                            }))
                          }
                          className={cn(supplierInput.replace("w-full", ""), "h-9 w-20")}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {closed ? (
            <dl className="grid grid-cols-3 gap-3 text-[13px]">
              <div>
                <dt className="text-[11px] text-ink-faint">أغلقه</dt>
                <dd>
                  {item.closed_by} <span className="ltr-isolate">{formatDateTime(item.closed_at)}</span>
                </dd>
              </div>
              <div>
                <dt className="text-[11px] text-ink-faint">التغليف</dt>
                <dd>{item.packaging_ok ? "سليم" : "متضرر"}</dd>
              </div>
              <div>
                <dt className="text-[11px] text-ink-faint">سندات التلف</dt>
                <dd className="ltr-isolate text-right">{item.writeoffs.join("، ") || "—"}</dd>
              </div>
              {item.note && <p className="col-span-3 text-ink-soft">{item.note}</p>}
            </dl>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4">
                <Field label="يعود إلى فرع">
                  <select
                    className={supplierInput}
                    value={branchId ?? ""}
                    onChange={(e) => setBranchId(e.target.value ? Number(e.target.value) : null)}
                  >
                    {(item.branches ?? []).map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <label className="mt-6 flex items-center gap-2 text-[13px] text-ink-soft">
                  <input
                    type="checkbox"
                    checked={packagingOk}
                    onChange={(e) => setPackagingOk(e.target.checked)}
                  />
                  التغليف سليم
                </label>
                <Field label="ملاحظة الفحص (كسر، نقص، ضرر…)" wide>
                  <input className={supplierInput} value={note} onChange={(e) => setNote(e.target.value)} />
                </Field>
              </div>
              <p className="rounded-control bg-violet-soft/60 p-3 text-[12px] leading-5 text-ink-soft">
                عند الإغلاق يُرجَع الطلب بمسار FINORA (عكس البيع والتحصيل وإرجاع الكمية بدفعات FIFO)، ثم يُخرج
                التالف من المخزون القابل للبيع بسند تلف مرتبط بحساب خسائر المخزون.
                {anyDamaged && !details.data?.can_writeoff && (
                  <strong className="block text-danger">تسجيل التالف يحتاج صلاحية سندات التلف.</strong>
                )}
              </p>
              {canManage && (
                <div className="flex justify-end gap-2">
                  <button type="button" className={supplierSecondary} onClick={onClose}>
                    إلغاء
                  </button>
                  <button
                    type="button"
                    className={supplierPrimary}
                    disabled={
                      !online || close.isPending || !branchId || (anyDamaged && !details.data?.can_writeoff)
                    }
                    onClick={() => close.mutate()}
                  >
                    {close.isPending ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <ClipboardCheck size={16} />
                    )}
                    إغلاق المرتجع
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </SupplierModal>
  );
}
