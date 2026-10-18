import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ArrowLeftRight, Building2, RefreshCw } from "lucide-react";
import { toFinoraError } from "@/api/finora";
import { storageLocations, type StorageDocument, type StorageStock } from "@/api/finora/storageLocations";
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
import { formatNumber } from "@/utils/format";
import { stockButton, stockPrimary, stockMoney } from "./StockForms";
import { StorageForm, storageKinds, type StorageFormMode } from "./StorageForm";

const phases = { send: "إرسال", receive: "استلام", cancel: "إلغاء" };
const statuses = { draft: "مسودة", sent: "قيد النقل", received: "مستلم", cancelled: "ملغى" };
export function StorageLocations({
  scope,
  active,
  serverUrl,
  onBusyChange,
  onActivity,
}: {
  scope: string;
  active: boolean;
  serverUrl: string | null;
  onBusyChange(busy: boolean): void;
  onActivity(id: number): void;
}) {
  const client = useQueryClient();
  const [view, setView] = useState<"stocks" | "transfers" | "locations">("stocks");
  const [placeKey, setPlaceKey] = useState("");
  const [text, setText] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(25);
  const [form, setForm] = useState<StorageFormMode | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [phase, setPhase] = useState<{
    name: keyof typeof phases;
    document: StorageDocument;
    key: string;
  } | null>(null);
  const search = useDebouncedValue(text, 200);
  const meta = useQuery({
    queryKey: ["storage-locations", scope, "meta"],
    queryFn: storageLocations.meta,
    enabled: active,
  });
  const place =
    meta.data?.places.find((row) => row.key === placeKey && row.is_active) ??
    meta.data?.places.find((row) => row.is_active);
  const busy = form !== null || phase !== null;
  useEffect(() => {
    onBusyChange(busy);
    return () => onBusyChange(false);
  }, [busy, onBusyChange]);
  const stocks = useQuery({
    queryKey: ["storage-locations", scope, "stocks", place?.key, page, size, search],
    queryFn: () => {
      if (!place) throw Error("اختر الموقع");
      return storageLocations.stocks(place.branch_id, place.id, page, search, size);
    },
    enabled: active && !!place && view === "stocks",
  });
  const transfers = useQuery({
    queryKey: ["storage-locations", scope, "transfers", place?.branch_id, page, size],
    queryFn: () => {
      if (!place) throw Error("اختر الفرع");
      return storageLocations.transfers(place.branch_id, page, size);
    },
    enabled: active && !!place && view === "transfers",
  });
  const detail = useQuery({
    queryKey: ["storage-locations", scope, "document", selected],
    queryFn: () => {
      if (selected === null) throw Error("اختر السند");
      return storageLocations.document(selected);
    },
    enabled: active && selected !== null,
  });
  const refresh = () => void client.invalidateQueries({ queryKey: ["storage-locations", scope] });
  const saved = (documentId?: number) => {
    setForm(null);
    setPhase(null);
    for (const key of [
      "storage-locations",
      "stock-operations",
      "stock-recovery",
      "products",
      "pos",
      "inventory-activity",
      "inventory-audit",
      "finance",
      "reports",
    ])
      void client.invalidateQueries({ queryKey: [key] });
    if (documentId !== undefined) {
      setSelected(documentId);
      setView("transfers");
      setPage(1);
    }
  };
  const action = useMutation({
    mutationFn: () => {
      if (!phase) throw Error("اختر مرحلة التحويل");
      return storageLocations.transferPhase(phase.document.id, phase.name, {
        operation_id: phase.key,
        branch_id: phase.document.branch_id,
        revision: phase.document.revision,
        ...(phase.name === "send" ? { source_revision: phase.document.source?.revision } : {}),
      });
    },
    onSuccess: () => {
      toast.success("تم حفظ حركة المخزن");
      saved();
    },
    onError: (error) => {
      toast.error(toFinoraError(error).message);
      refresh();
    },
  });
  const columns: Column<StorageStock>[] = [
    {
      id: "product",
      header: "الصنف / الخيار",
      width: "42%",
      cell: (row) => (
        <div className="flex items-center gap-3">
          <ProductThumb src={productImageUrl(row.image_url, serverUrl)} size={44} />
          <div className="min-w-0">
            <strong className="block truncate">{row.name}</strong>
            <span className="text-xs text-ink-faint">
              {row.sku} · {row.variant_name || "بدون خيارات"}
            </span>
          </div>
        </div>
      ),
    },
    {
      id: "quantity",
      header: "الموجود",
      align: "center",
      cell: (row) => <strong className="ltr-isolate text-base">{formatNumber(row.quantity)}</strong>,
    },
    {
      id: "available",
      header: (
        <span className="inline-flex items-center gap-2">
          المتاح
          <FeatureHelp
            label="شرح المتاح بالمخزن"
            text="المتاح يستثني الحجز. التالف والرواجع تحت المراجعة لا تتاح للبيع. النقل يعتمد رصيد الموقع ودليل كلفة القطع."
          />
        </span>
      ),
      align: "center",
      cell: (row) => formatNumber(row.available),
    },
    ...(meta.data?.show_cost
      ? [{ id: "cost", header: "قيمة القطع", cell: (row: StorageStock) => stockMoney(row.cost) }]
      : []),
    {
      id: "actions",
      header: "الإجراء",
      cell: (row) => (
        <div className="flex flex-wrap gap-2">
          <button className={stockButton} onClick={() => onActivity(row.product_id)} disabled={busy}>
            السجل
          </button>
          {meta.data?.can_edit && place && (
            <button
              className={stockButton}
              disabled={busy || !row.basis_valid || row.movable < 1}
              onClick={() => setForm({ kind: "transfer", place, row })}
            >
              <ArrowLeftRight size={14} />
              نقل
            </button>
          )}
          {!row.basis_valid && <span className="text-xs text-warning">يحتاج مراجعة الكلفة</span>}
        </div>
      ),
    },
  ];
  const transferColumns: Column<StorageDocument>[] = [
    { id: "number", header: "السند", cell: (row) => <strong className="ltr-isolate">{row.number}</strong> },
    {
      id: "route",
      header: "مسار القطع",
      cell: (row) => (
        <span>
          {row.from_name} ← {row.to_name}
        </span>
      ),
    },
    { id: "quantity", header: "الكمية", align: "center", cell: (row) => formatNumber(row.quantity) },
    {
      id: "status",
      header: "الحالة",
      cell: (row) => (
        <span className="rounded-full bg-violet-soft px-3 py-1 text-xs text-violet">
          {statuses[row.status]}
        </span>
      ),
    },
    { id: "reason", header: "السبب", cell: (row) => row.reason },
  ];
  const changeView = (next: typeof view) => {
    setView(next);
    setPage(1);
    setText("");
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" aria-label="مخازن الفرع">
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <h3 className="sr-only">مخازن الفرع</h3>
        <select
          aria-label="المخزن الفرعي"
          className={`${stockButton} max-w-72`}
          disabled={busy}
          value={place?.key ?? ""}
          onChange={(e) => {
            setPlaceKey(e.target.value);
            setPage(1);
            setSelected(null);
          }}
        >
          {meta.data?.places
            .filter((row) => row.is_active)
            .map((row) => (
              <option key={row.key} value={row.key}>
                {row.branch_name} · {row.name}
              </option>
            ))}
        </select>
        {(["stocks", "transfers", "locations"] as const).map((next) => (
          <button
            key={next}
            className={
              view === next
                ? stockButton.replace("bg-white", "bg-violet-soft").replace("text-ink-soft", "text-violet")
                : stockButton
            }
            aria-pressed={view === next}
            disabled={busy}
            onClick={() => changeView(next)}
          >
            {{ stocks: "الأرصدة", transfers: "التحويلات الداخلية", locations: "إدارة المواقع" }[next]}
          </button>
        ))}
        <FeatureHelp
          label="شرح مخازن الفرع"
          text="هذه المواقع تقسم رصيد الفرع نفسه. حفظ التحويل ينشئ مسودة؛ إرسال القطع يجعلها قيد النقل، واستلامها يثبتها في الموقع المقصود. قيمة القطع وكلفتها الأصلية محفوظتان."
        />
        {meta.data?.can_edit && place && (
          <button
            className={stockPrimary}
            disabled={busy}
            onClick={() => setForm({ kind: "location", place })}
          >
            <Building2 size={16} />
            إضافة مخزن
          </button>
        )}
        <button
          className={stockButton}
          aria-label="تحديث مخازن الفرع"
          disabled={busy || meta.isFetching}
          onClick={refresh}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {meta.error && (
        <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
          {toFinoraError(meta.error).message}
        </p>
      )}

      {view === "stocks" && (
        <fieldset className="shrink-0" disabled={busy}>
          <SearchBox
            value={text}
            onChange={(value) => {
              setText(value);
              setPage(1);
            }}
            placeholder="ابحث بالصنف، الرمز أو الخيار…"
          />
        </fieldset>
      )}
      {view === "locations" ? (
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {meta.data?.places
              .filter((row) => row.branch_id === place?.branch_id)
              .map((row) => (
                <div key={row.key} className="rounded-control border border-line bg-white/80 p-4">
                  <div className="flex items-center gap-3">
                    <Building2 size={22} className="shrink-0 text-violet" />
                    <div className="min-w-0 flex-1">
                      <strong>{row.name}</strong>
                      <p className="mt-1 text-xs text-ink-faint">
                        {row.code} · {storageKinds[row.kind]} · {row.is_active ? "فعّال" : "موقوف"}
                      </p>
                    </div>
                  </div>
                  {meta.data?.can_edit && row.id !== null && (
                    <button
                      className={`${stockButton} mt-3`}
                      disabled={busy}
                      onClick={() => setForm({ kind: "location", place: row, editing: row })}
                    >
                      تعديل المخزن
                    </button>
                  )}
                </div>
              ))}
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          {view === "stocks" ? (
            <DataTable
              label="أرصدة المخزن الفرعي"
              columns={columns}
              rows={stocks.data?.items}
              loading={stocks.isPending}
              fetching={stocks.isFetching}
              error={stocks.error ? toFinoraError(stocks.error).message : null}
              onRetry={refresh}
              emptyTitle="لا توجد أصناف بهذا البحث"
            />
          ) : (
            <DataTable
              label="تحويلات مخازن الفرع"
              columns={transferColumns}
              rows={transfers.data?.items}
              loading={transfers.isPending}
              fetching={transfers.isFetching}
              error={transfers.error ? toFinoraError(transfers.error).message : null}
              onRetry={refresh}
              emptyTitle="لا توجد تحويلات داخلية"
              onOpen={(row) => {
                if (!busy) setSelected(row.id);
              }}
            />
          )}
          <div className="shrink-0">
            <TablePagination
              page={page}
              totalPages={Math.max(
                1,
                Math.ceil(
                  (view === "stocks" ? (stocks.data?.total ?? 0) : (transfers.data?.total ?? 0)) / size,
                ),
              )}
              total={view === "stocks" ? (stocks.data?.total ?? 0) : (transfers.data?.total ?? 0)}
              pageSize={size}
              noun={view === "stocks" ? "صنف / خيار" : "تحويل"}
              onPage={setPage}
              onPageSize={(value) => {
                setSize(value);
                setPage(1);
              }}
            />
          </div>
        </div>
      )}
      <SidePanel
        open={active && selected !== null}
        title={detail.data?.number ?? "تفاصيل تحويل المخزن"}
        onClose={() => {
          if (!busy) setSelected(null);
        }}
      >
        {detail.error ? (
          <p role="alert">{toFinoraError(detail.error).message}</p>
        ) : detail.data ? (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <ProductThumb src={productImageUrl(detail.data.image_url, serverUrl)} />
              <div>
                <strong>{detail.data.product_name}</strong>
                <p className="text-xs text-ink-faint">
                  {detail.data.sku} · {detail.data.variant_name}
                </p>
              </div>
            </div>
            <p className="rounded-control bg-violet-soft p-3">
              {statuses[detail.data.status]} · {detail.data.from_name} ← {detail.data.to_name}
            </p>
            <p>
              الكمية <strong>{formatNumber(detail.data.quantity)}</strong> · {detail.data.variant_name}
            </p>
            {meta.data?.show_cost && <p>قيمة القطع {stockMoney(detail.data.cost)}</p>}
            <p>{detail.data.reason}</p>
            <p className="text-xs text-ink-faint">
              {new Date(detail.data.created_at).toLocaleString("ar-IQ")}
            </p>
            {detail.data.can_send &&
              (!detail.data.source?.basis_valid || detail.data.source.movable < detail.data.quantity) && (
                <p role="alert" className="rounded-control bg-warning-soft p-3 text-sm">
                  راجع رصيد المصدر وكلفة القطع قبل الإرسال؛ الرصيد القابل للنقل لا يغطي السند حالياً.
                </p>
              )}
            <div className="flex flex-wrap gap-2">
              {(["send", "receive", "cancel"] as const)
                .filter((name) => detail.data?.[`can_${name}`])
                .map((name) => (
                  <button
                    key={name}
                    className={name === "cancel" ? stockButton : stockPrimary}
                    disabled={
                      busy ||
                      (name === "send" &&
                        (!detail.data?.source?.basis_valid ||
                          detail.data.source.movable < detail.data.quantity))
                    }
                    onClick={() => {
                      if (detail.data) {
                        action.reset();
                        setPhase({ name, document: detail.data, key: crypto.randomUUID() });
                      }
                    }}
                  >
                    {phases[name]} القطع
                  </button>
                ))}
            </div>
          </div>
        ) : (
          <p>جارٍ تحميل السند…</p>
        )}
      </SidePanel>
      {form && meta.data && (
        <StorageForm
          mode={form}
          places={meta.data.places}
          active={active}
          onClose={() => setForm(null)}
          onSaved={saved}
        />
      )}
      <ConfirmDialog
        open={active && phase !== null}
        title={`${phase ? phases[phase.name] : ""} تحويل المخزن`}
        message={
          phase && (
            <>
              <p>
                {phase.document.from_name} ← {phase.document.to_name} ·{" "}
                {formatNumber(phase.document.quantity)} قطعة
              </p>
              <p>
                {phase.name === "send"
                  ? "أكد أن القطع غادرت المصدر فعلياً؛ يبقى رصيدها قيد النقل حتى الاستلام."
                  : phase.name === "receive"
                    ? "أكد وصول القطع فعلياً إلى المخزن المقصود."
                    : phase.document.status === "sent"
                      ? "أكد رجوع القطع فعلياً إلى المصدر قبل إلغاء النقل."
                      : "يلغى سند المسودة دون تغيير الرصيد."}
              </p>
            </>
          )
        }
        confirmLabel={action.isError ? "إعادة نفس الطلب" : "تأكيد العملية"}
        busy={action.isPending}
        onClose={() => {
          if (!action.isPending) {
            setPhase(null);
            action.reset();
          }
        }}
        onConfirm={() => {
          if (!action.isPending) action.mutate();
        }}
      />
    </div>
  );
}
