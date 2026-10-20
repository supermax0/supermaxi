import { useTimeFormat } from "@/stores/displayTime";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Phone, Truck, UserRound, X } from "lucide-react";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type {
  AgentDetails,
  AgentRow,
  BucketStats,
  CarrierDetails,
  CarrierRow,
  ManifestSummary,
  OrderBucket,
  ShippingMeta,
} from "@/api/finora/shipping";
import { DataTable, type Column } from "@/components/DataTable";
import { SearchBox } from "@/components/SearchBox";
import { TablePagination } from "@/components/TablePagination";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { cn } from "@/utils/cn";
import { formatNumber, formatDateTime } from "@/utils/format";
import { supplierPrimary } from "../suppliers/SupplierDialogs";
import { DuplicateAgents } from "./DuplicateAgents";
import { CarrierSettingsForm, ReceiptsList, StatementView } from "./Finance";
import { KIND_LABEL, ManifestState, Metric, Money, money } from "./shared";

type Owner = "carriers" | "agents";
type ProfileTab = "orders" | "manifests" | "statement" | "receipts" | "history" | "settings";

const BUCKETS: Array<{ id: OrderBucket; label: string; stat?: keyof BucketStats }> = [
  { id: "all", label: "الكل", stat: "total" },
  { id: "transit", label: "قيد التوصيل", stat: "transit" },
  { id: "delivered_unsettled", label: "واصل غير مسدد", stat: "delivered_unsettled" },
  { id: "due", label: "مستحق", stat: "due" },
  { id: "returned", label: "راجع", stat: "returned" },
];

/** Carriers or agents: a table of parties with a live profile beside it. */
export function PartiesSection({
  owner,
  enabled,
  onOpenManifest,
  meta,
  onPortalSettlement,
}: {
  owner: Owner;
  enabled: boolean;
  onOpenManifest(id: number): void;
  meta?: ShippingMeta;
  onPortalSettlement?(agentId: number): void;
}) {
  useTimeFormat();
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 150);
  const [activeId, setActiveId] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["shipping", owner],
    queryFn: async () =>
      owner === "carriers" ? (await finora.shipping.carriers()).rows : (await finora.shipping.agents()).rows,
    enabled,
  });
  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const all = (list.data ?? []) as Array<CarrierRow | AgentRow>;
    return needle ? all.filter((r) => `${r.name} ${r.phone}`.toLowerCase().includes(needle)) : all;
  }, [list.data, search]);

  const columns = useMemo<Column<CarrierRow | AgentRow>[]>(
    () => [
      {
        id: "name",
        header: owner === "carriers" ? "شركة النقل" : "المندوب",
        width: "28%",
        cell: (r) => (
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-maroon-soft text-maroon">
              {owner === "carriers" ? <Truck size={18} /> : <UserRound size={18} />}
            </span>
            <div className="min-w-0">
              <p className="truncate font-semibold">{r.name}</p>
              <p className="ltr-isolate truncate text-right text-[11px] text-ink-faint">{r.phone || "—"}</p>
            </div>
          </div>
        ),
      },
      {
        id: "transit",
        header: "قيد التوصيل",
        width: "14%",
        cell: (r) => <span className="ltr-isolate font-semibold">{formatNumber(r.stats.transit.count)}</span>,
      },
      {
        id: "delivered",
        header: "واصل غير مسدد",
        width: "18%",
        cell: (r) => (
          <div className="flex flex-col items-start">
            <span className="font-semibold">
              <span className="ltr-isolate">{formatNumber(r.stats.delivered_unsettled.count)}</span> طلب
            </span>
            <Money value={r.stats.delivered_unsettled.amount} className="text-[11px] text-ink-faint" />
          </div>
        ),
      },
      {
        id: "due",
        header: "المستحق",
        width: "18%",
        cell: (r) => <Money value={r.stats.due.amount} className="text-[15px] font-bold text-maroon" />,
      },
      {
        id: "returned",
        header: "المرتجعات",
        width: "11%",
        minTableWidth: 760,
        cell: (r) => <span className="ltr-isolate">{formatNumber(r.stats.returned.count)}</span>,
      },
      {
        id: "extra",
        header: owner === "carriers" ? "كشوف مفتوحة" : "الحالة",
        width: "11%",
        minTableWidth: 860,
        cell: (r) =>
          "open_manifests" in r ? (
            <span className="ltr-isolate">{formatNumber(r.open_manifests)}</span>
          ) : (
            <span
              className={cn(
                "rounded-full px-2.5 py-1 text-[11px] font-semibold",
                r.active ? "bg-success-soft text-success" : "bg-surface-sunken text-ink-faint",
              )}
            >
              {r.active ? "فعال" : "موقوف"}
            </span>
          ),
      },
    ],
    [owner],
  );

  return (
    <div className="flex h-full min-h-0 gap-4">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {owner === "agents" && <DuplicateAgents enabled={enabled} />}
        <SearchBox
          value={searchText}
          onChange={setSearchText}
          busy={list.isFetching}
          placeholder={owner === "carriers" ? "ابحث باسم الشركة أو الهاتف…" : "ابحث باسم المندوب أو الهاتف…"}
          className="mb-3 shrink-0"
        />
        <DataTable
          label={owner === "carriers" ? "شركات النقل" : "المندوبون"}
          columns={columns}
          rows={rows}
          loading={list.isPending}
          fetching={list.isFetching}
          error={list.error ? toFinoraError(list.error).message : null}
          onRetry={() => void list.refetch()}
          emptyTitle={owner === "carriers" ? "لا توجد شركات نقل" : "لا يوجد مندوبون"}
          emptyHint="تُضاف من إعدادات الشحن في FINORA."
          activeId={activeId}
          onOpen={(r) => setActiveId(r.id)}
        />
      </div>
      {activeId != null && (
        <PartyProfile
          key={`${owner}-${activeId}`}
          owner={owner}
          id={activeId}
          onClose={() => setActiveId(null)}
          onOpenManifest={onOpenManifest}
          meta={meta}
          onPortalSettlement={onPortalSettlement}
        />
      )}
    </div>
  );
}

function PartyProfile({
  owner,
  id,
  onClose,
  onOpenManifest,
  meta,
  onPortalSettlement,
}: {
  owner: Owner;
  id: number;
  onClose(): void;
  onOpenManifest(id: number): void;
  meta?: ShippingMeta;
  onPortalSettlement?(agentId: number): void;
}) {
  useTimeFormat();
  const [tab, setTab] = useState<ProfileTab>("orders");
  const details = useQuery({
    queryKey: ["shipping", owner, id],
    queryFn: (): Promise<CarrierDetails | AgentDetails> =>
      owner === "carriers" ? finora.shipping.carrier(id) : finora.shipping.agent(id),
  });
  const data = details.data;
  const party = data ? ("carrier" in data ? data.carrier : data.agent) : null;
  const stats = data?.stats;
  const tabs: Array<{ id: ProfileTab; label: string }> = [
    { id: "orders", label: "الطلبات" },
    { id: "manifests", label: "الكشوف" },
    { id: "statement", label: "كشف الحساب" },
    { id: "receipts", label: "السندات" },
    ...(owner === "carriers"
      ? [
          { id: "history" as const, label: "سجل FINORA" },
          { id: "settings" as const, label: "الإعدادات" },
        ]
      : []),
  ];
  const custody = data && "agent" in data ? data.custody : undefined;

  return (
    <aside className="glass flex w-[440px] shrink-0 flex-col rounded-panel p-5" aria-label="الملف التفصيلي">
      <header className="mb-4 flex items-start gap-3">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-control bg-maroon-soft text-maroon">
          {owner === "carriers" ? <Truck size={22} /> : <UserRound size={22} />}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-bold text-ink">{party?.name ?? "…"}</h3>
          <p className="mt-0.5 flex items-center gap-1 text-[12px] text-ink-faint">
            <Phone size={12} /> <span className="ltr-isolate">{party?.phone || "—"}</span>
            {data && "agent" in data && (
              <span
                className={cn(
                  "ms-2 inline-flex items-center gap-1",
                  data.agent.has_portal ? "text-success" : "",
                )}
              >
                <ExternalLink size={11} /> {data.agent.has_portal ? "مرتبط ببوابة المندوب" : "بدون بوابة"}
              </span>
            )}
          </p>
        </div>
        <button
          type="button"
          aria-label="إغلاق الملف"
          onClick={onClose}
          className="text-ink-faint hover:text-ink"
        >
          <X size={18} />
        </button>
      </header>

      {details.error ? (
        <p className="text-sm text-danger">{toFinoraError(details.error).message}</p>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-2">
            <Metric label="قيد التوصيل" value={formatNumber(stats?.transit.count ?? 0)} />
            <Metric
              label="واصل غير مسدد"
              value={money(stats?.delivered_unsettled.amount ?? 0)}
              tone="text-warning"
            />
            <Metric label="المستحق علينا تحصيله" value={money(stats?.due.amount ?? 0)} tone="text-maroon" />
            {data && "received_total" in data ? (
              <Metric label="الرصيد بذمة الشركة" value={money(data.balance)} tone="text-success" />
            ) : (
              <Metric label="المرتجعات" value={formatNumber(stats?.returned.count ?? 0)} />
            )}
          </div>
          {custody && (
            <div className="mb-4 rounded-control bg-maroon-soft/50 p-3 text-[12px]">
              <div className="flex items-center justify-between">
                <span className="font-bold text-ink">العهدة المالية لدى المندوب</span>
                <Money value={custody.in_custody} className="text-[15px] font-bold text-maroon" />
              </div>
              <p className="mt-1 text-ink-soft">
                محصّل حسب البوابة <Money value={custody.claimed_amount} /> (
                <span className="ltr-isolate">{formatNumber(custody.claimed_count)}</span> طلب) · متبقٍ من
                تسويات سابقة <Money value={custody.settled_outstanding} /> · سلّم للمحاسب{" "}
                <Money value={custody.received_total} />
              </p>
              {onPortalSettlement && meta?.can_manage && custody.claimed_count > 0 && (
                <button
                  type="button"
                  className={cn(supplierPrimary, "mt-2 h-9 w-full text-[13px]")}
                  onClick={() => onPortalSettlement(id)}
                >
                  تسوية العهدة من كشف البوابة
                </button>
              )}
            </div>
          )}
          <div
            role="tablist"
            aria-label="أقسام الملف"
            className="flex flex-wrap gap-1 rounded-control bg-white/70 p-1 shadow-control"
          >
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
                className={cn(
                  "h-8 whitespace-nowrap rounded-[10px] px-3 text-[12.5px] font-medium",
                  tab === t.id
                    ? "bg-violet-soft text-violet-deep ring-1 ring-violet/15"
                    : "text-ink-soft hover:text-ink",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
            {tab === "orders" && <PartyOrders owner={owner} id={id} stats={stats} />}
            {tab === "manifests" && <ManifestMiniList rows={data?.manifests ?? []} onOpen={onOpenManifest} />}
            {tab === "statement" && <StatementView owner={owner} id={id} />}
            {tab === "receipts" && (
              <ReceiptsList
                compact
                filter={{ party_type: owner === "carriers" ? "carrier" : "agent", party_id: id }}
              />
            )}
            {tab === "settings" && meta && (
              <CarrierSettingsForm
                carrierId={id}
                canManage={meta.can_manage}
                treasuryAccounts={meta.treasury_accounts}
              />
            )}
            {tab === "history" && data && "statement" in data && (
              <ul className="divide-y divide-line/60 text-[13px]">
                {data.statement.length === 0 && (
                  <li className="py-8 text-center text-ink-faint">لا توجد حركات</li>
                )}
                {data.statement.map((s) => (
                  <li key={s.id} className="flex items-center gap-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{s.note || s.action}</p>
                      <p className="ltr-isolate text-right text-[11px] text-ink-faint">
                        {formatDateTime(s.date)}
                        {s.invoice_id ? ` · #${s.invoice_id}` : ""}
                      </p>
                    </div>
                    <Money value={s.amount} className="font-bold" />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </aside>
  );
}

function PartyOrders({ owner, id, stats }: { owner: Owner; id: number; stats?: BucketStats }) {
  useTimeFormat();
  const [bucket, setBucket] = useState<OrderBucket>("all");
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 250);
  const [page, setPage] = useState(1);
  const orders = useQuery({
    queryKey: ["shipping", owner, id, "orders", bucket, search, page],
    queryFn: () => finora.shipping.orders(owner, id, bucket, search, page),
  });
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1">
        {BUCKETS.map((b) => (
          <button
            key={b.id}
            type="button"
            aria-pressed={bucket === b.id}
            onClick={() => {
              setBucket(b.id);
              setPage(1);
            }}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium",
              bucket === b.id ? "bg-maroon text-white" : "bg-surface-sunken text-ink-soft hover:text-ink",
            )}
          >
            {b.label}
            {stats && b.stat && (
              <span className="ltr-isolate opacity-75">{formatNumber(stats[b.stat].count)}</span>
            )}
          </button>
        ))}
      </div>
      <SearchBox
        value={searchText}
        onChange={(v) => {
          setSearchText(v);
          setPage(1);
        }}
        busy={orders.isFetching}
        placeholder="رقم الطلب أو اسم العميل أو الهاتف…"
      />
      <ul className="divide-y divide-line/60 text-[13px]">
        {orders.isPending && <li className="py-8 text-center text-ink-faint">جارٍ التحميل…</li>}
        {orders.data?.rows.length === 0 && <li className="py-8 text-center text-ink-faint">لا توجد طلبات</li>}
        {orders.data?.rows.map((o) => (
          <li key={o.id} className="flex items-center gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate">
                <span className="ltr-isolate font-bold">#{o.id}</span> · {o.customer_name || "—"}
              </p>
              <p className="truncate text-[11px] text-ink-faint">
                {o.status} · {o.customer_city || "—"}
              </p>
            </div>
            <Money value={o.remaining} className="font-semibold" />
          </li>
        ))}
      </ul>
      {orders.data && orders.data.total_pages > 1 && (
        <TablePagination
          page={orders.data.page}
          totalPages={orders.data.total_pages}
          total={orders.data.total}
          pageSize={orders.data.page_size}
          noun="طلب"
          onPage={setPage}
          onPageSize={() => undefined}
        />
      )}
    </div>
  );
}

export function ManifestMiniList({ rows, onOpen }: { rows: ManifestSummary[]; onOpen(id: number): void }) {
  useTimeFormat();
  if (rows.length === 0) return <p className="py-8 text-center text-[13px] text-ink-faint">لا توجد كشوف</p>;
  return (
    <ul className="space-y-1.5">
      {rows.map((m) => (
        <li key={m.id}>
          <button
            type="button"
            onClick={() => onOpen(m.id)}
            className="flex w-full items-center gap-3 rounded-control px-3 py-2.5 text-start text-[13px] hover:bg-surface-sunken"
          >
            <div className="min-w-0 flex-1">
              <p className="ltr-isolate truncate text-right font-bold">{m.number}</p>
              <p className="text-[11px] text-ink-faint">
                {KIND_LABEL[m.kind]} · {formatNumber(m.orders_count)} طلب · {m.created_at.slice(0, 10)}
              </p>
            </div>
            <ManifestState executed={m.executed} partial={m.settlement_state === "partial"} />
          </button>
        </li>
      ))}
    </ul>
  );
}
