import { useTimeFormat } from "@/stores/displayTime";
import { formatDateTime } from "@/utils/format";
import { useQuery } from "@tanstack/react-query";
import { FileCheck2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useWorkspaceHistory } from "@/features/workspace/navigation";
import { finora, toFinoraError } from "@/api/finora";
import type { ManifestFilters, ManifestSummary, ShippingMeta } from "@/api/finora/shipping";
import { DataTable, type Column } from "@/components/DataTable";
import { SelectInput } from "@/components/FilterPanel";
import { SearchBox } from "@/components/SearchBox";
import { StatusTabs } from "@/components/StatusTabs";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { formatNumber } from "@/utils/format";
import { KIND_LABEL, ManifestState, Money } from "./shared";

const STATES: Array<{ id: ManifestFilters["state"]; label: string }> = [
  { id: "all", label: "الكل" },
  { id: "open", label: "مسودة" },
  { id: "executed", label: "معتمد" },
];

/** All manifests (or, as «التسويات المالية», approved settlement manifests only). */
export function ManifestsSection({
  enabled,
  settlementsOnly = false,
  carriers,
  onOpen,
  initialState = "all",
}: {
  enabled: boolean;
  settlementsOnly?: boolean;
  carriers: ShippingMeta["carriers"];
  onOpen(id: number): void;
  initialState?: ManifestFilters["state"];
}) {
  useTimeFormat();
  const [state, setState] = useState<ManifestFilters["state"]>(settlementsOnly ? "executed" : initialState);
  const [kind, setKind] = useState<ManifestFilters["kind"]>(settlementsOnly ? "settlement" : "");
  const [carrierId, setCarrierId] = useState("");
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 250);
  const filters: ManifestFilters = { state, kind, search, carrierId: carrierId ? Number(carrierId) : null };
  useWorkspaceHistory(
    {
      window: "shipping",
      tab: state === "open" ? "open-manifests" : state === "executed" ? "executed-manifests" : "manifests",
    },
    enabled && !settlementsOnly,
  );
  const list = useQuery({
    queryKey: ["shipping", "manifests", filters],
    queryFn: () => finora.shipping.manifests(filters),
    enabled,
  });
  const rows = list.data?.rows;

  const columns = useMemo<Column<ManifestSummary>[]>(
    () => [
      {
        id: "number",
        header: "رقم الكشف",
        width: "22%",
        cell: (m) => (
          <div className="min-w-0">
            <p className="ltr-isolate truncate text-right font-bold">{m.number}</p>
            <p className="text-[11px] text-ink-faint">
              {KIND_LABEL[m.kind]}
              {m.reference && ` · مرجع الشركة ${m.reference}`}
            </p>
          </div>
        ),
      },
      {
        id: "party",
        header: "الشركة / المندوب",
        width: "20%",
        cell: (m) => <span className="truncate">{m.carrier || m.agent || "—"}</span>,
      },
      {
        id: "count",
        header: "الطلبات",
        width: "10%",
        cell: (m) => <span className="ltr-isolate font-semibold">{formatNumber(m.orders_count)}</span>,
      },
      {
        id: "amount",
        header: "المبلغ",
        width: "17%",
        cell: (m) => <Money value={m.total_amount} className="font-bold" />,
      },
      {
        id: "date",
        header: "التاريخ",
        width: "14%",
        minTableWidth: 780,
        cell: (m) => (
          <div className="text-[12px]">
            <p className="ltr-isolate text-right">{formatDateTime(m.created_at)}</p>
            <p className="text-[11px] text-ink-faint">{m.created_by}</p>
          </div>
        ),
      },
      {
        id: "state",
        header: "الحالة",
        width: "12%",
        cell: (m) => <ManifestState executed={m.executed} partial={m.settlement_state === "partial"} />,
      },
    ],
    [],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex shrink-0 flex-wrap items-center gap-2">
        <SearchBox
          value={searchText}
          onChange={setSearchText}
          busy={list.isFetching}
          placeholder="رقم الكشف أو مرجع الشركة…"
          className="min-w-[220px] flex-1"
        />
        {!settlementsOnly && (
          <>
            <StatusTabs<ManifestFilters["state"]>
              label="حالة الكشوف"
              value={state}
              tabs={STATES}
              onChange={setState}
            />
            <StatusTabs
              label="نوع الكشف"
              value={kind || "all"}
              tabs={[
                { id: "all", label: "كل الأنواع" },
                { id: "settlement", label: "تسوية" },
                { id: "handover", label: "تسليم" },
                { id: "agent", label: "مندوب" },
              ]}
              onChange={(v) => setKind(v === "all" ? "" : (v as ManifestFilters["kind"]))}
            />
          </>
        )}
        <div className="w-[200px]">
          <SelectInput
            placeholder="كل الشركات"
            value={carrierId}
            onChange={setCarrierId}
            options={carriers.map((c) => ({ value: String(c.id), label: c.name }))}
          />
        </div>
      </div>
      {settlementsOnly && (
        <p className="mb-3 flex shrink-0 items-center gap-1.5 text-[12px] text-ink-faint">
          <FileCheck2 size={14} /> التسويات المعتمدة فقط — كل تسوية مرحّلة إلى الخزينة ولا تُعدّل؛ التصحيح
          يكون بكشف جديد.
        </p>
      )}
      <DataTable
        label={settlementsOnly ? "التسويات المالية" : "الكشوف"}
        columns={columns}
        rows={rows}
        loading={list.isPending}
        fetching={list.isFetching}
        error={list.error ? toFinoraError(list.error).message : null}
        onRetry={() => void list.refetch()}
        emptyTitle={settlementsOnly ? "لا توجد تسويات معتمدة" : "لا توجد كشوف"}
        emptyHint="أنشئ كشف تسوية جديد من الزر بالأعلى."
        onOpen={(m) => onOpen(m.id)}
      />
    </div>
  );
}
