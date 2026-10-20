import { useTimeFormat } from "@/stores/displayTime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Building2,
  History,
  PackagePlus,
  Printer,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type {
  StockDocument,
  StockLedger,
  StockRow,
  StockTransfer,
  StockWriteOff,
  StockWarehouseMovement,
} from "@/api/finora/stockOperations";
import { productImageUrl } from "@/api/finora/products";
import { DataTable, type Column } from "@/components/DataTable";
import { ConfirmDialog } from "@/components/Dialog";
import { FeatureHelp } from "@/components/FeatureHelp";
import { ProductThumb } from "@/components/ProductThumb";
import { SearchBox } from "@/components/SearchBox";
import { SidePanel } from "@/components/SidePanel";
import { TablePagination } from "@/components/TablePagination";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { toast } from "@/stores/toasts";
import { formatNumber, formatDateTime } from "@/utils/format";
import { StockForms, stockButton, stockPrimary, stockMoney, type StockForm } from "./StockForms";
import { StorageLocations } from "./StorageLocations";

type View = "stocks" | "transfers" | "writeoffs" | "reorder" | "locations" | "movements";
export type StockTarget = { kind: StockLedger; document: StockDocument; id: number };
const labels = {
  stocks: "أرصدة المواقع",
  transfers: "التحويلات",
  writeoffs: "التلفيات",
  reorder: "إعادة الطلب",
  locations: "المواقع والمخازن",
  movements: "حركة المخزن",
};
const statuses: Record<string, string> = {
  draft: "مسودة",
  approved: "معتمد",
  sent: "قيد النقل",
  partially_received: "مستلم جزئياً",
  rejected: "مرفوض",
  received: "مستلم",
  cancelled: "ملغى",
  posted: "مرحل",
  reversed: "تم عكسه",
  reversal: "سند عكس",
};
export function StockOperations({
  scope,
  active,
  serverUrl,
  onBusyChange,
  onActivity,
  initialTarget,
}: {
  scope: string;
  active: boolean;
  serverUrl: string | null;
  onBusyChange(busy: boolean): void;
  onActivity(id: number): void;
  initialTarget?: StockTarget;
}) {
  useTimeFormat();
  const client = useQueryClient();
  const [storageBusy, setStorageBusy] = useState(false);
  const [kind, setKind] = useState<StockLedger>(initialTarget?.kind ?? "branch"),
    [view, setView] = useState<View>(initialTarget?.document ?? "stocks");
  const [place, setPlace] = useState(""),
    [text, setText] = useState(""),
    [status, setStatus] = useState("");
  const [page, setPage] = useState(1),
    [size, setSize] = useState(25),
    [form, setForm] = useState<StockForm | null>(null);
  const [selected, setSelected] = useState<StockTarget | null>(initialTarget ?? null),
    [recovery, setRecovery] = useState<string | null>(null);
  const [movementProduct, setMovementProduct] = useState<number | undefined>(undefined);
  const search = useDebouncedValue(text, 250);
  const meta = useQuery({
    queryKey: ["stock-operations", scope, "meta", kind],
    queryFn: () => finora.stockOperations.meta(kind),
    enabled: active,
  });
  const location = meta.data?.locations.some((row) => row.key === place)
    ? place
    : (meta.data?.locations[0]?.key ?? "");
  const coreLocations = view === "locations" && kind === "branch" && meta.data?.storage_available;
  useEffect(() => {
    onBusyChange(form !== null || storageBusy);
    return () => onBusyChange(false);
  }, [form, storageBusy, onBusyChange]);
  const stocks = useQuery({
    queryKey: ["stock-operations", scope, "stocks", kind, location, search, page, size, view],
    queryFn: () => finora.stockOperations.stocks(kind, location, search, page, size, view === "reorder"),
    enabled: active && !!location && (view === "stocks" || view === "reorder"),
  });
  const transfers = useQuery({
    queryKey: ["stock-operations", scope, "transfers", kind, location, search, status, page, size],
    queryFn: () => finora.stockOperations.transfers(kind, search, status, page, size, location),
    enabled: active && view === "transfers" && !!meta.data,
  });
  const writeoffs = useQuery({
    queryKey: ["stock-operations", scope, "writeoffs", kind, location, search, page, size],
    queryFn: () => finora.stockOperations.writeoffs(kind, location, search, page, size),
    enabled: active && view === "writeoffs" && !!meta.data,
  });
  const movements = useQuery({
    queryKey: ["stock-operations", scope, "movements", location, movementProduct, page, size],
    queryFn: () => finora.stockOperations.movements(location, movementProduct, page, size),
    enabled: active && kind === "warehouse" && view === "movements" && !!location,
  });
  const transfer = useQuery({
    queryKey: ["stock-operations", scope, "transfer", selected?.kind, selected?.id],
    queryFn: () => {
      if (!selected) throw Error("اختر سنداً");
      return finora.stockOperations.transfer(selected.kind, selected.id);
    },
    enabled: active && selected?.document === "transfers",
  });
  const writeoff = useQuery({
    queryKey: ["stock-operations", scope, "writeoff", selected?.id],
    queryFn: () => {
      if (!selected) throw Error("اختر سنداً");
      return finora.stockOperations.writeoff(selected.id);
    },
    enabled: active && selected?.document === "writeoffs",
  });
  const pending = useQuery({
    queryKey: ["stock-recovery", scope],
    queryFn: () => finora.stockOperations.pending(),
    enabled: active,
    refetchOnWindowFocus: true,
  });
  const refresh = () => void client.invalidateQueries({ queryKey: ["stock-operations", scope] });
  const saved = (result: { id: number; type: string; ledger_kind?: StockLedger; status?: string }) => {
    setForm(null);
    setRecovery(null);
    for (const key of [
      "stock-operations",
      "storage-locations",
      "stock-recovery",
      "products",
      "pos",
      "inventory-activity",
      "inventory-audit",
      "finance",
      "reports",
    ])
      void client.invalidateQueries({ queryKey: [key] });
    if (result.ledger_kind && (result.type === "stock_transfer" || result.type === "warehouse_transfer")) {
      setView("transfers");
      setSelected({ kind: result.ledger_kind, document: "transfers", id: result.id });
    } else if (result.ledger_kind && result.type === "inventory_writeoff") {
      setView("writeoffs");
      setSelected({ kind: result.ledger_kind, document: "writeoffs", id: result.id });
    }
  };
  const retry = useMutation({
    mutationFn: (key: string) => finora.stockOperations.retry(key),
    onSuccess: (result) => {
      toast.success("تمت مراجعة الطلب الأصلي");
      saved(result);
    },
    onError: (error) => {
      toast.error(toFinoraError(error).message);
      void client.invalidateQueries({ queryKey: ["stock-recovery", scope] });
    },
  });
  const printing = useMutation({
    mutationFn: () => {
      if (!selected) throw Error("اختر سنداً");
      return finora.stockOperations.print(selected.kind, selected.document, selected.id);
    },
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  const stockColumns: Column<StockRow>[] = [
    {
      id: "product",
      header: "الصنف / الخيار",
      width: "34%",
      cell: (row) => (
        <div className="flex items-center gap-3">
          <ProductThumb src={productImageUrl(row.image_url, serverUrl)} />
          <div className="min-w-0">
            <strong className="block truncate">{row.name}</strong>
            <span className="mt-1 block text-xs text-ink-faint">
              {row.variant_name || "بدون خيار"} · {row.sku}
            </span>
          </div>
        </div>
      ),
    },
    { id: "quantity", header: "الموجود", align: "center", cell: (row) => formatNumber(row.quantity) },
    {
      id: "available",
      header: "المتاح",
      align: "center",
      cell: (row) => (
        <strong className={row.available <= row.minimum ? "text-warning" : "text-success"}>
          {formatNumber(row.available)}
        </strong>
      ),
    },
    {
      id: "reserved",
      header: "محجوز",
      align: "center",
      minTableWidth: 840,
      cell: (row) => formatNumber(row.reserved),
    },
    {
      id: "transit",
      header: "وارد قيد النقل",
      align: "center",
      minTableWidth: 840,
      cell: (row) => formatNumber(row.in_transit),
    },
    { id: "minimum", header: "حد الطلب", align: "center", cell: (row) => formatNumber(row.minimum) },
    ...(view === "reorder"
      ? [
          {
            id: "suggested",
            header: "كمية مقترحة",
            align: "center" as const,
            cell: (row: StockRow) => <strong className="text-violet">{formatNumber(row.suggested)}</strong>,
          },
        ]
      : []),
    {
      id: "actions",
      header: "الإجراء",
      width: "156px",
      cell: (row) => (
        <div className="flex justify-end gap-1">
          <button
            className={stockButton}
            aria-label={`حركة ${row.name} ${row.variant_name}`}
            title="عرض الحركة"
            disabled={form !== null || stocks.isFetching}
            onClick={() => {
              if (kind === "branch") onActivity(row.product_id);
              else {
                setMovementProduct(row.product_id);
                changeView("movements");
              }
            }}
          >
            <History size={14} />
          </button>
          {meta.data?.can_edit_rules && (
            <button
              className={stockButton}
              aria-label={`حد طلب ${row.name} ${row.variant_name}`}
              title="حد إعادة الطلب"
              disabled={form !== null || stocks.isFetching}
              onClick={() => setForm({ kind: "rule", row })}
            >
              <RefreshCw size={14} />
            </button>
          )}
          {meta.data?.can_writeoff && (
            <button
              className={stockButton}
              aria-label={`تلف ${row.name} ${row.variant_name}`}
              title="تسجيل التلف"
              disabled={form !== null || stocks.isFetching || row.available < 1}
              onClick={() => setForm({ kind: "writeoff", row })}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      ),
    },
  ];
  const transferColumns: Column<StockTransfer>[] = [
    { id: "number", header: "السند", cell: (row) => <strong dir="ltr">{row.number}</strong> },
    { id: "from", header: "المصدر", cell: (row) => row.from_name },
    { id: "to", header: "الوجهة", cell: (row) => row.to_name },
    { id: "quantity", header: "القطع", align: "center", cell: (row) => formatNumber(row.quantity) },
    {
      id: "status",
      header: "الحالة",
      cell: (row) => (
        <span className="rounded-full bg-violet-soft px-3 py-1 text-xs text-violet">
          {statuses[row.status]}
        </span>
      ),
    },
  ];
  const writeoffColumns: Column<StockWriteOff>[] = [
    {
      id: "number",
      header: "السند / التاريخ",
      cell: (row) => (
        <div>
          <strong dir="ltr">{row.number}</strong>
          <span className="mt-1 block text-xs text-ink-faint">{row.business_date}</span>
        </div>
      ),
    },
    {
      id: "product",
      header: "الصنف / الخيار",
      cell: (row) => (
        <div>
          <strong>{row.product_name}</strong>
          <span className="mt-1 block text-xs text-ink-faint">{row.variant_name}</span>
        </div>
      ),
    },
    { id: "quantity", header: "القطع", align: "center", cell: (row) => formatNumber(row.quantity) },
    ...(meta.data?.show_cost
      ? [{ id: "cost", header: "الكلفة", cell: (row: StockWriteOff) => stockMoney(row.cost) }]
      : []),
    {
      id: "status",
      header: "الحالة",
      cell: (row) => (
        <span className="rounded-full bg-violet-soft px-3 py-1 text-xs text-violet">
          {statuses[row.status]}
        </span>
      ),
    },
  ];
  const movementColumns: Column<StockWarehouseMovement>[] = [
    { id: "product", header: "الصنف", cell: (row) => row.product_name },
    {
      id: "quantity",
      header: "التغير",
      align: "center",
      cell: (row) => (
        <strong dir="ltr" className={row.quantity < 0 ? "text-danger" : "text-success"}>
          {row.quantity > 0 ? "+" : ""}
          {formatNumber(row.quantity)}
        </strong>
      ),
    },
    {
      id: "before",
      header: "قبل",
      align: "center",
      cell: (row) => (row.before == null ? "—" : formatNumber(row.before)),
    },
    {
      id: "after",
      header: "بعد",
      align: "center",
      cell: (row) => (row.after == null ? "—" : formatNumber(row.after)),
    },
    { id: "note", header: "السبب", cell: (row) => row.note },
    { id: "date", header: "التاريخ", cell: (row) => formatDateTime(row.created_at) },
  ];
  const list =
    view === "transfers"
      ? transfers
      : view === "writeoffs"
        ? writeoffs
        : view === "movements"
          ? movements
          : stocks;
  const error = list.error ? toFinoraError(list.error).message : null;
  const changeView = (next: View) => {
    setView(next);
    setPage(1);
    setText("");
    setSelected(null);
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {!coreLocations && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <h3 className="me-auto text-base font-semibold text-ink">إدارة المخزون</h3>
          <FeatureHelp
            label="شرح إدارة المخزون"
            text="الموجود هو الرصيد الفعلي في هذا الموقع، والمتاح يستثني الحجز. التحويل يبقى قيد النقل من الإرسال حتى الاستلام. التلف يرتبط بكلفة القطع وقيد الخسارة. لكل فرع سجلّه؛ مخازن الجملة تظهر إذا كان نشاط الشركة وصلاحياتك يدعمانها."
          />
          {meta.data && meta.data.kinds.length > 1 && (
            <select
              aria-label="نوع سجل المخزون"
              className={stockButton}
              value={kind}
              disabled={form !== null || storageBusy}
              onChange={(e) => {
                setKind(e.target.value as StockLedger);
                setPlace("");
                setPage(1);
                setSelected(null);
                setView("stocks");
              }}
            >
              <option value="branch">مخزون الفروع</option>
              <option value="warehouse">مخازن الجملة</option>
            </select>
          )}
          {meta.data?.can_create_transfer &&
            !(view === "locations" && kind === "branch" && meta.data.storage_available) && (
              <button
                className={stockPrimary}
                disabled={!location || form !== null}
                onClick={() => setForm({ kind: "transfer" })}
              >
                <ArrowLeftRight size={16} />
                تحويل جديد
              </button>
            )}
          {kind === "warehouse" && meta.data?.can_manage_locations && (
            <button
              className={stockButton}
              onClick={() => setForm({ kind: "warehouse" })}
              disabled={form !== null}
            >
              <PackagePlus size={16} />
              إضافة مخزن
            </button>
          )}
          <button
            className={stockButton}
            aria-label="تحديث عمليات المخزون"
            onClick={refresh}
            disabled={form !== null || list.isFetching}
          >
            <RefreshCw size={16} />
          </button>
        </div>
      )}
      {meta.error && (
        <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
          {toFinoraError(meta.error).message}
          <button className={`${stockButton} ms-3`} onClick={() => void meta.refetch()}>
            إعادة المحاولة
          </button>
        </p>
      )}
      {pending.data?.items.length ? (
        <details className="shrink-0 rounded-control border border-warning/20 bg-warning-soft p-3">
          <summary className="cursor-pointer text-sm">
            طلبات مخزون محفوظة للمراجعة ({pending.data.items.length})
          </summary>
          <p className="mt-2 text-xs text-ink-soft">
            راجع نفس الطلب إذا فقدت الرد؛ FINORA يتحقق من رقمه ويحميك من تكرار الخصم.
          </p>
          <div className="mt-2 space-y-2">
            {pending.data.items.map((row) => (
              <div
                key={row.key}
                className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-white p-2 text-xs"
              >
                <span>
                  {row.request.path.includes("/writeoffs")
                    ? "سند تلف / عكس"
                    : row.request.path.includes("/rules")
                      ? "حد طلب"
                      : row.request.path.includes("/locations")
                        ? "مخزن"
                        : "تحويل مخزون"}{" "}
                  · {formatDateTime(row.created)}
                </span>
                <button
                  className={stockButton}
                  disabled={retry.isPending}
                  onClick={() => setRecovery(row.key)}
                >
                  مراجعة نفس الطلب
                </button>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      <div className="flex shrink-0 flex-wrap gap-2" aria-label="أقسام إدارة المخزون">
        {(Object.keys(labels) as View[])
          .filter((next) => next !== "movements" || kind === "warehouse")
          .map((next) => (
            <button
              className={
                view === next
                  ? stockButton
                      .replace("bg-white", "bg-violet-soft")
                      .replace("text-ink-soft", "text-violet")
                      .replace("border-line", "border-violet/40")
                  : stockButton
              }
              key={next}
              aria-pressed={view === next}
              disabled={form !== null || storageBusy}
              onClick={() => {
                changeView(next);
                setMovementProduct(undefined);
              }}
            >
              {labels[next]}
            </button>
          ))}
      </div>
      {view !== "locations" && (
        <div className="flex shrink-0 flex-wrap gap-2">
          <select
            aria-label="موقع المخزون"
            disabled={form !== null}
            className={`${stockButton} max-w-64`}
            value={location}
            onChange={(e) => {
              setPlace(e.target.value);
              setPage(1);
            }}
          >
            {meta.data?.locations.map((row) => (
              <option key={row.key} value={row.key}>
                {row.name}
              </option>
            ))}
          </select>
          {view !== "movements" && (
            <fieldset className="min-w-52 flex-1" disabled={form !== null}>
              <SearchBox
                value={text}
                onChange={(value) => {
                  setText(value);
                  setPage(1);
                }}
                placeholder={
                  view === "transfers" ? "ابحث بالسند أو الملاحظة…" : "ابحث بالاسم، الخيار أو الرمز…"
                }
              />
            </fieldset>
          )}
          {view === "transfers" && (
            <select
              aria-label="حالة التحويل"
              disabled={form !== null}
              className={stockButton}
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">كل الحالات</option>
              {["draft", "approved", "sent", "partially_received", "received", "rejected", "cancelled"].map(
                (value) => (
                  <option value={value} key={value}>
                    {statuses[value]}
                  </option>
                ),
              )}
            </select>
          )}
        </div>
      )}
      {kind === "warehouse" && view === "writeoffs" && (
        <p className="shrink-0 rounded-control bg-violet-soft p-3 text-xs text-ink-soft">
          تلف مخازن الجملة يحتاج أساس كلفة مستقل ومراجع قبل ترحيله محاسبياً. تحويلات المخازن وسجلها وحدود
          الطلب متاحة حسب صلاحيتك.
        </p>
      )}
      {coreLocations ? (
        <StorageLocations
          key={scope}
          scope={scope}
          active={active}
          serverUrl={serverUrl}
          onBusyChange={setStorageBusy}
          onActivity={onActivity}
        />
      ) : view === "locations" ? (
        <div className="min-h-0 flex-1 overflow-auto rounded-control border border-line bg-white/80 p-4">
          <p className="mb-4 text-sm text-ink-soft">
            {kind === "branch"
              ? "هذه مواقع مخزون الفروع الموجودة. التحويل والجرد والسجل يستخدمون نفس الرصيد."
              : "كل مخزن مرتبط بفرعه؛ تُسجل حركاته في سجل مخازن الجملة."}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {meta.data?.locations.map((row) => (
              <button
                key={row.key}
                className="flex items-center gap-3 rounded-control border border-line p-4 text-start hover:bg-violet-soft"
                onClick={() => {
                  setPlace(row.key);
                  changeView("stocks");
                }}
              >
                <Building2 className="text-violet" size={22} />
                <div>
                  <strong>{row.name}</strong>
                  <p className="mt-1 text-xs text-ink-faint">{row.branch_name}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          {(view === "stocks" || view === "reorder") && stocks.data && (
            <p className="shrink-0 rounded-control bg-violet-soft px-3 py-2 text-xs text-ink-soft">
              {formatNumber(stocks.data.stats.items)} صنف / خيار · الموجود{" "}
              {formatNumber(stocks.data.stats.quantity)} · المحجوز {formatNumber(stocks.data.stats.reserved)}{" "}
              · عند حد الطلب {formatNumber(stocks.data.stats.reorder)}
              {view === "reorder" && " · المقترح يطرح القطع قيد النقل من الرصيد المستهدف."}
            </p>
          )}
          <div className="flex min-h-0 flex-1 flex-col">
            {view === "movements" ? (
              <DataTable
                label="حركة مخازن الجملة"
                columns={movementColumns}
                rows={movements.data?.items}
                loading={movements.isPending}
                fetching={movements.isFetching}
                error={error}
                onRetry={refresh}
                emptyTitle="لا توجد حركات بهذا الموقع"
                onOpen={(row) => {
                  if (row.document && row.document_id)
                    setSelected({ kind: "warehouse", document: row.document, id: row.document_id });
                }}
              />
            ) : view === "transfers" ? (
              <DataTable
                label="سجل تحويلات المخزون"
                columns={transferColumns}
                rows={transfers.data?.items}
                loading={transfers.isPending}
                fetching={transfers.isFetching}
                error={error}
                onRetry={refresh}
                emptyTitle="لا توجد تحويلات بهذا البحث"
                onOpen={(row) => {
                  if (!form) setSelected({ kind, document: "transfers", id: row.id });
                }}
              />
            ) : view === "writeoffs" ? (
              <DataTable
                label="سجل تلفيات المخزون"
                columns={writeoffColumns}
                rows={writeoffs.data?.items}
                loading={writeoffs.isPending}
                fetching={writeoffs.isFetching}
                error={error}
                onRetry={refresh}
                emptyTitle="لا توجد سندات تلف"
                onOpen={(row) => {
                  if (!form) setSelected({ kind, document: "writeoffs", id: row.id });
                }}
              />
            ) : (
              <DataTable
                label="أرصدة المخزون حسب الموقع"
                columns={stockColumns}
                rows={stocks.data?.items}
                loading={stocks.isPending}
                fetching={stocks.isFetching}
                error={error}
                onRetry={refresh}
                emptyTitle={
                  view === "reorder" ? "لا توجد أصناف عند حد الطلب" : "لا توجد أصناف بهذا الموقع أو البحث"
                }
              />
            )}
          </div>
          <TablePagination
            page={page}
            totalPages={Math.max(1, Math.ceil((list.data?.total ?? 0) / size))}
            total={list.data?.total ?? 0}
            pageSize={size}
            noun="سجل"
            onPage={(value) => {
              if (!form) setPage(value);
            }}
            onPageSize={(value) => {
              setSize(value);
              setPage(1);
            }}
          />
        </>
      )}
      <SidePanel
        open={active && selected !== null && form === null}
        title={selected?.document === "transfers" ? "تفاصيل تحويل المخزون" : "تفاصيل سند التلف"}
        onClose={() => setSelected(null)}
        footer={
          <button
            className={stockButton}
            disabled={
              printing.isPending || (selected?.document === "transfers" ? !transfer.data : !writeoff.data)
            }
            onClick={() => printing.mutate()}
          >
            <Printer size={16} />
            طباعة السند
          </button>
        }
      >
        {(selected?.document === "transfers" ? transfer : writeoff).isPending && (
          <p role="status">تحميل السند…</p>
        )}
        {(selected?.document === "transfers" ? transfer : writeoff).error && (
          <p role="alert" className="text-danger">
            {toFinoraError((selected?.document === "transfers" ? transfer : writeoff).error).message}
          </p>
        )}
        {selected?.document === "transfers" && transfer.data && (
          <div className="space-y-4">
            <strong className="block text-xl" dir="ltr">
              {transfer.data.number}
            </strong>
            <p className="rounded-control bg-violet-soft p-3">
              {statuses[transfer.data.status]} · {transfer.data.from_name} ← {transfer.data.to_name}
            </p>
            {transfer.data.lines.map((row) => (
              <div className="rounded-control border border-line p-3" key={row.id}>
                <strong>{row.name}</strong>
                <p className="mt-1 text-sm text-ink-soft">{row.variant_name || "بدون خيار"}</p>
                <p className="mt-2 text-sm">
                  المرسل {formatNumber(row.quantity)} · المستلم {formatNumber(row.received)}
                  {(row.residual ?? 0) > 0 && transfer.data?.status !== "received" && (
                    <span className="text-warning"> · بالطريق {formatNumber(row.residual ?? 0)}</span>
                  )}
                </p>
                {meta.data?.show_cost && (
                  <p className="mt-1 text-sm">الكلفة الموثقة {stockMoney(row.cost)}</p>
                )}
              </div>
            ))}
            <p className="text-sm text-ink-soft">{transfer.data.note}</p>
            <div className="flex flex-wrap gap-2">
              {(["approve", "send", "receive", "receive_partial", "resolve", "reject", "cancel"] as const)
                .filter((phase) => transfer.data?.[`can_${phase}`])
                .map((phase) => (
                  <button
                    key={phase}
                    className={phase === "cancel" || phase === "reject" ? stockButton : stockPrimary}
                    onClick={() => {
                      if (transfer.data) setForm({ kind: "phase", phase, row: transfer.data });
                    }}
                  >
                    {
                      {
                        approve: "اعتماد التحويل",
                        send: "إرسال التحويل",
                        receive: "استلام كامل",
                        receive_partial: "استلام جزئي",
                        resolve: "معالجة المتبقي",
                        reject: "رفض الاستلام",
                        cancel: "إلغاء التحويل",
                      }[phase]
                    }
                  </button>
                ))}
            </div>
          </div>
        )}
        {selected?.document === "writeoffs" && writeoff.data && (
          <div className="space-y-4">
            <strong className="block text-xl" dir="ltr">
              {writeoff.data.number}
            </strong>
            <p className="rounded-control bg-violet-soft p-3">
              {statuses[writeoff.data.status]} · {writeoff.data.location_name}
            </p>
            <strong>{writeoff.data.product_name}</strong>
            <p>{writeoff.data.variant_name}</p>
            <p>
              الكمية {formatNumber(writeoff.data.quantity)} · قبل{" "}
              {formatNumber(writeoff.data.before_quantity)} · بعد {formatNumber(writeoff.data.after_quantity)}
            </p>
            {meta.data?.show_cost && <p>كلفة القطع {stockMoney(writeoff.data.cost)}</p>}
            <p className="text-sm text-ink-soft">{writeoff.data.reason}</p>
            <p className="text-xs text-ink-faint">
              {writeoff.data.business_date} · قيد خسارة مخزون بدون حركة نقدية
            </p>
            {meta.data?.can_writeoff && writeoff.data.status === "posted" && (
              <button
                className={stockButton}
                onClick={() => {
                  if (writeoff.data) setForm({ kind: "reverse", row: writeoff.data });
                }}
              >
                <RotateCcw size={15} />
                عكس السند
              </button>
            )}
          </div>
        )}
      </SidePanel>
      {form && meta.data && (
        <StockForms
          key={JSON.stringify(form)}
          mode={form}
          meta={meta.data}
          location={location}
          scope={scope}
          active={active}
          serverUrl={serverUrl}
          onClose={() => setForm(null)}
          onSaved={saved}
        />
      )}
      <ConfirmDialog
        open={active && recovery !== null}
        title="مراجعة الطلب الأصلي"
        message="سيُرسل نفس رقم الطلب وبياناته المحفوظة. إذا نُفذ سابقاً يظهر تأكيده بدون تسجيله مرتين."
        confirmLabel="مراجعة الطلب"
        onClose={() => {
          if (!retry.isPending) setRecovery(null);
        }}
        onConfirm={() => {
          if (recovery && !retry.isPending) retry.mutate(recovery);
        }}
        busy={retry.isPending}
      />
    </div>
  );
}
