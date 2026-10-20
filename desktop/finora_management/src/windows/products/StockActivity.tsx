import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, ExternalLink, History, Printer, RefreshCw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { InventoryActivityRow } from "@/api/finora/inventoryActivity";
import { DataTable, type Column } from "@/components/DataTable";
import { FeatureHelp } from "@/components/FeatureHelp";
import { DateInput, Field, SelectInput } from "@/components/FilterPanel";
import { SearchBox } from "@/components/SearchBox";
import { SidePanel } from "@/components/SidePanel";
import { TablePagination } from "@/components/TablePagination";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { desktopBridge } from "@/services/bridge";
import { useConnection } from "@/stores/connection";
import { useOrderNavigation } from "@/stores/orderNavigation";
import { usePurchaseNavigation } from "@/stores/purchaseNavigation";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
import { formatIqd } from "@/utils/money";

const kinds: Record<string, string> = {
  invoice: "فاتورة بيع",
  purchase: "فاتورة شراء",
  stock_transfer: "تحويل مخزون",
  inventory_writeoff: "تلف / عكس تلف",
  inventory_count: "تسوية جرد",
  direct_stock_change: "تغيير مباشر",
  database_trigger: "تغيير ملتقط",
  trade_in: "استبدال",
  purchase_return: "مرتجع شراء",
};
const stamp = new Intl.DateTimeFormat("ar-IQ-u-nu-latn", {
  timeZone: "Asia/Baghdad",
  dateStyle: "short",
  timeStyle: "short",
  hour12: true,
});
const button =
  "flex min-h-10 items-center justify-center gap-2 rounded-control border border-line bg-white px-3 text-sm text-ink-soft hover:bg-violet-soft disabled:opacity-40";
const value = (number: number | null) => (number === null ? "—" : formatNumber(number));
const kind = (row: InventoryActivityRow) =>
  row.operation_label ??
  kinds[row.source_type ?? ""] ??
  (row.record_kind === "capture" ? "تغيير ملتقط" : "حركة مخزون");
const costText = (amount: number | string) =>
  typeof amount === "string" ? `${BigInt(amount).toLocaleString("en-US")} د.ع` : formatIqd(amount);

export function StockActivity({
  scope,
  active,
  productId,
  onClearProduct,
  onProduct,
  onAudit,
  onStockDocument,
}: {
  scope: string;
  active: boolean;
  productId?: number;
  onClearProduct(): void;
  onProduct(id: number): void;
  onAudit(id: number): void;
  onStockDocument?(document: "transfers" | "writeoffs", id: number): void;
}) {
  const [text, setText] = useState(""),
    [branch, setBranch] = useState(""),
    [direction, setDirection] = useState("");
  const [from, setFrom] = useState(""),
    [to, setTo] = useState("");
  const [page, setPage] = useState(1),
    [size, setSize] = useState(25),
    [selected, setSelected] = useState<InventoryActivityRow | null>(null);
  const search = useDebouncedValue(text, 300);
  const offline = useConnection((s) => s.status === "offline");
  const query = useMemo(
    () => ({ page, pageSize: size, search, branch, direction, from, to, productId }),
    [page, size, search, branch, direction, from, to, productId],
  );
  const list = useQuery({
    queryKey: ["inventory-activity", scope, query],
    queryFn: () => finora.inventoryActivity.list(query),
    enabled: active,
  });
  const exporting = useMutation({
    mutationFn: async () => {
      const result = await finora.inventoryActivity.export(query);
      const url = URL.createObjectURL(new Blob([result.content], { type: "text/csv;charset=utf-8" }));
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = result.filename;
        anchor.click();
      } finally {
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    },
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  const printing = useMutation({
    mutationFn: () => finora.inventoryActivity.print(query),
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  const reportBlocked = list.isFetching || text !== search || !list.data?.available || list.data.total === 0;
  const close = () => setSelected(null);
  const pick = (setter: (next: string) => void, next: string) => {
    setter(next);
    setPage(1);
    setSelected(null);
  };
  const openSource = async (row: InventoryActivityRow) => {
    const id = row.document_id ?? row.source_id;
    const source = row.document_kind ?? row.source_type;
    if (!row.can_open_source || !id) return;
    if (source === "invoice") {
      useOrderNavigation.getState().open(id);
      useWindowManager.getState().open("orders");
    } else if (source === "inventory_count") onAudit(id);
    else if (onStockDocument && (source === "stock_transfer" || source === "inventory_writeoff"))
      onStockDocument(source === "stock_transfer" ? "transfers" : "writeoffs", id);
    else if (source === "purchase") {
      usePurchaseNavigation.getState().open(id);
      useWindowManager.getState().open("purchases");
    } else {
      const path = source === "stock_transfer" ? `/inventory/transfers/${id}` : null;
      if (!path) return;
      try {
        await desktopBridge().app.openInFinora(path);
      } catch (error) {
        toast.error(toFinoraError(error).message);
      }
    }
  };
  const columns = useMemo<Column<InventoryActivityRow>[]>(
    () => [
      {
        id: "product",
        header: "الصنف / الفرع",
        width: "24%",
        cell: (row) => (
          <div className="min-w-0">
            <p className="truncate font-semibold">{row.product_name}</p>
            <p className="truncate text-xs text-ink-faint">
              {row.branch_name} · {row.sku} {row.variant && `· ${row.variant}`}
            </p>
          </div>
        ),
      },
      {
        id: "source",
        header: "نوع الحركة",
        width: "19%",
        cell: (row) => (
          <div>
            <p>
              {kind(row)}
              {row.reversal ? " · عكس حركة" : ""}
            </p>
            <p className="text-xs text-ink-faint">{row.actor_name ?? "المنفذ غير مسجل"}</p>
          </div>
        ),
      },
      {
        id: "quantity",
        header: "الكمية",
        align: "center",
        width: "10%",
        cell: (row) => (
          <span
            dir="ltr"
            className={`ltr-isolate font-bold ${row.direction === "in" ? "text-success" : "text-danger"}`}
          >
            {row.direction === "in" ? "+" : "−"}
            {formatNumber(row.quantity)}
          </span>
        ),
      },
      {
        id: "before",
        header: "قبل الحركة",
        align: "center",
        width: "12%",
        cell: (row) => (
          <span dir="ltr" className="ltr-isolate">
            {value(row.before)}
          </span>
        ),
      },
      {
        id: "after",
        header: "بعد الحركة",
        align: "center",
        width: "12%",
        cell: (row) => (
          <span dir="ltr" className="ltr-isolate font-semibold">
            {value(row.after)}
          </span>
        ),
      },
      {
        id: "time",
        header: "التاريخ والوقت",
        width: "23%",
        cell: (row) => (
          <span dir="ltr" className="ltr-isolate text-xs">
            {stamp.format(new Date(row.created_at))}
          </span>
        ),
      },
    ],
    [],
  );
  return (
    <div className="stock-activity flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <History size={19} className="text-violet" />
            <h2 className="font-semibold">حركة المخزون</h2>
            <FeatureHelp
              label="شرح سجل حركة المخزون"
              text="تتابع دخول وخروج الأصناف وربطها بالبيع والشراء والتحويل والجرد. الحركة المرتبطة بسجل كمية تظهر مرة واحدة. الرصيد غير الموثق يظهر — بدل تخمينه، وتغييرات الكمية القديمة تظهر كتغيير ملتقط."
            />
          </div>
          <p className="stock-activity-intro mt-1 text-xs text-ink-faint">
            اختر حركة حتى تشوف تفاصيلها والمستند المرتبط بيها.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FeatureHelp
            label="شرح طباعة وتصدير المخزون"
            text="الطباعة والتصدير يشملان كل الحركات ضمن البحث والفترة والفرع المختار، مو الصفحة الحالية فقط. تظهر التكلفة إذا عندك صلاحيتها، والرصيد غير الموثق يبقى —."
          />
          <button
            type="button"
            className={button}
            disabled={reportBlocked || printing.isPending}
            onClick={() => printing.mutate()}
          >
            <Printer size={16} />
            طباعة / PDF
          </button>
          <button
            type="button"
            className={button}
            disabled={reportBlocked || exporting.isPending}
            onClick={() => exporting.mutate()}
          >
            <Download size={16} />
            تصدير CSV
          </button>
          <button
            className={button}
            type="button"
            onClick={() => void list.refetch()}
            disabled={list.isFetching}
            aria-label="تحديث حركة المخزون"
          >
            <RefreshCw size={16} className={list.isFetching ? "animate-spin" : ""} />
            تحديث
          </button>
        </div>
      </div>
      {offline && (
        <p role="status" className="shrink-0 rounded-control bg-warning-soft p-3 text-sm text-warning">
          الاتصال مقطوع؛ حدّث السجل عند رجوع الإنترنت حتى تشوف الحركات الجديدة.
        </p>
      )}
      <div className="stock-activity-filters shrink-0 space-y-3">
        <div className="stock-activity-filter-fields grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Field label="الفرع">
            <SelectInput
              value={branch}
              onChange={(next) => pick(setBranch, next)}
              placeholder="كل الفروع المسموحة"
              options={(list.data?.branches ?? []).map((row) => ({ value: String(row.id), label: row.name }))}
            />
          </Field>
          <Field label="اتجاه الحركة">
            <SelectInput
              value={direction}
              onChange={(next) => pick(setDirection, next)}
              placeholder="الدخول والخروج"
              options={[
                { value: "in", label: "دخول مخزون" },
                { value: "out", label: "خروج مخزون" },
              ]}
            />
          </Field>
          <Field label="من تاريخ">
            <DateInput value={from} onChange={(next) => pick(setFrom, next)} />
          </Field>
          <Field label="إلى تاريخ">
            <DateInput value={to} onChange={(next) => pick(setTo, next)} />
          </Field>
        </div>
        <div className="stock-activity-search flex items-center gap-2">
          <SearchBox
            value={text}
            onChange={(next) => pick(setText, next.slice(0, 150))}
            placeholder="ابحث باسم الصنف، SKU أو الباركود..."
            busy={list.isFetching}
            className="min-w-0 flex-1"
            scanner={false}
          />
          {productId && (
            <button className={button} onClick={onClearProduct} type="button">
              <X size={15} />
              كل الأصناف
            </button>
          )}
        </div>
      </div>
      {list.data?.notice && (
        <p className="stock-activity-notice shrink-0 text-xs leading-5 text-ink-faint">{list.data.notice}</p>
      )}
      <DataTable<InventoryActivityRow>
        label="حركة المخزون"
        columns={columns}
        rows={list.data?.items}
        loading={list.isLoading}
        fetching={list.isFetching}
        error={list.error ? toFinoraError(list.error).message : null}
        onRetry={() => void list.refetch()}
        emptyTitle={list.data?.available === false ? "سجل الحركة غير مهيأ" : "ماكو حركات ضمن التصفية"}
        emptyHint="غيّر الفترة أو الفرع حتى تظهر الحركات المسجلة."
        activeId={selected?.id}
        onOpen={setSelected}
      />
      <TablePagination
        page={page}
        totalPages={Math.max(1, Math.ceil((list.data?.total ?? 0) / size))}
        total={list.data?.total ?? 0}
        pageSize={size}
        noun="حركة"
        onPage={(next) => {
          setPage(next);
          close();
        }}
        onPageSize={(next) => {
          setSize(next);
          setPage(1);
          close();
        }}
      />
      <SidePanel
        open={selected !== null}
        title="تفاصيل حركة المخزون"
        subtitle={selected?.product_name}
        onClose={close}
        footer={
          selected && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className={button} onClick={() => onProduct(selected.product_id)}>
                بطاقة المنتج
              </button>
              {selected.can_open_source && (
                <button type="button" className={button} onClick={() => void openSource(selected)}>
                  <ExternalLink size={15} />
                  عرض المستند
                </button>
              )}
            </div>
          )
        }
      >
        {selected && (
          <div className="space-y-4 text-sm">
            <p className="rounded-control bg-violet-soft p-3 text-violet">
              {kind(selected)}
              {selected.source_id ? ` #${selected.source_id}` : ""}
            </p>
            <dl className="grid grid-cols-2 gap-3">
              {[
                ["الفرع", selected.branch_name],
                ["اللون / المقاس", selected.variant || "بدون متغير"],
                ["المنفذ", selected.actor_name ?? "غير مسجل"],
                ["الوقت", stamp.format(new Date(selected.created_at))],
                ["قبل الحركة", value(selected.before)],
                ["بعد الحركة", value(selected.after)],
              ].map(([label, content]) => (
                <div key={label} className="rounded-control border border-line p-3">
                  <dt className="text-xs text-ink-faint">{label}</dt>
                  <dd className="mt-1 break-words font-semibold">{content}</dd>
                </div>
              ))}
            </dl>
            <p className="leading-6 text-ink-soft">
              {selected.balance_basis === "option"
                ? "الرصيد يخص اللون أو المقاس المحدد."
                : selected.balance_basis === "product"
                  ? "الرصيد يخص الصنف في هذا الفرع."
                  : "ماكو رصيد سابق ولاحق موثق لهذه الحركة؛ كمية الدخول أو الخروج محفوظة، وما نحسب الرصيد القديم بالتخمين."}
            </p>
            {selected.reason && (
              <div>
                <h3 className="font-semibold">سبب الحركة</h3>
                <p className="mt-2 whitespace-pre-wrap break-words leading-6 text-ink-soft">
                  {selected.reason}
                </p>
              </div>
            )}
            {list.data?.can_view_cost && (
              <div className="rounded-control border border-line p-3">
                <p className="text-xs text-ink-faint">
                  قيمة الحركة بالتكلفة{" "}
                  <FeatureHelp
                    label="شرح قيمة حركة المخزون"
                    text="قيمة القطع حسب التكلفة المحفوظة بالحركة، مو سعر البيع ولا قبض أو صرف جديد. إذا ما كانت التكلفة مسجلة ما نعرض قيمة تقديرية."
                  />
                </p>
                <p className="mt-1 font-bold">
                  {selected.total_cost == null ? "غير مسجلة" : costText(selected.total_cost)}
                </p>
              </div>
            )}
          </div>
        )}
      </SidePanel>
    </div>
  );
}
