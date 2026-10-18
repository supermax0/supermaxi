import {
  Ban,
  Banknote,
  ChevronDown,
  Pencil,
  Eye,
  MoreHorizontal,
  Printer,
  RefreshCcw,
  ScanBarcode,
  Truck,
  Undo2,
  UserRound,
  ListChecks,
  Send,
  FileText,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { ORDER_TABS, type OrderFilters, type OrderRow, type OrderTab } from "@/api/finora/orders";
import { DataTable, type Column } from "@/components/DataTable";
import { ConfirmDialog, PickerDialog, type PickerOption } from "@/components/Dialog";
import { DateInput, Field, FilterPanel, NumberInput, SelectInput } from "@/components/FilterPanel";
import { Menu, type MenuItem } from "@/components/Menu";
import { SearchBox } from "@/components/SearchBox";
import { StatusBadge } from "@/components/StatusBadge";
import { StatusTabs, type TabItem } from "@/components/StatusTabs";
import { TablePagination } from "@/components/TablePagination";
import {
  formatOrderDate,
  canReturnOrder,
  ORDER_TAB_LABELS,
  ORDER_TAB_PERMISSIONS,
  orderStatusStyle,
  RETURN_TARGET,
  STATUS_TARGETS,
} from "@/features/orders/status";
import {
  orderFailureMessage,
  useAssignOrders,
  useCancelOrder,
  useChangeOrderStatus,
  useOrderCounts,
  useOrderLookups,
  useOrdersList,
  useReturnOrders,
} from "@/features/orders/useOrders";
import { useOrderPreferences } from "@/features/orders/orderPreferences";
import { collectionDue } from "@/features/orders/payment";
import { useBarcodeScanner } from "@/hooks/useBarcodeScanner";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useSelection } from "@/hooks/useSelection";
import { useConnection } from "@/stores/connection";
import { useCan, useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { useOrderNavigation } from "@/stores/orderNavigation";
import { cn } from "@/utils/cn";
import { formatIqd } from "@/utils/money";
import { OrderDetailsPanel } from "./OrderDetailsPanel";
import { PaymentDialog } from "./PaymentDialog";
import { ShippingBarcodeDialog, type OrderScan } from "./ShippingBarcodeDialog";
import { QuickOrderEditor } from "./QuickOrderEditor";
import { DispatchDialog, type DispatchMode } from "../shipping/Dispatch";

interface FilterDraft {
  city: string;
  shipping: string;
  agent: string;
  dateFrom: string;
  dateTo: string;
  amountMin: string;
  amountMax: string;
}

const EMPTY_DRAFT: FilterDraft = {
  city: "",
  shipping: "",
  agent: "",
  dateFrom: "",
  dateTo: "",
  amountMin: "",
  amountMax: "",
};

function draftToFilters(draft: FilterDraft): Omit<OrderFilters, "search"> {
  return {
    cities: draft.city ? [draft.city] : undefined,
    shipping: draft.shipping || undefined,
    deliveryAgent: draft.agent || undefined,
    dateFrom: draft.dateFrom || undefined,
    dateTo: draft.dateTo || undefined,
    amountMin: draft.amountMin ? Number(draft.amountMin) : undefined,
    amountMax: draft.amountMax ? Number(draft.amountMax) : undefined,
  };
}

type Pending =
  | { kind: "status"; ids: number[] }
  | { kind: "confirm-status"; ids: number[]; status: string }
  | { kind: "return"; ids: number[] }
  | { kind: "confirm-return"; ids: number[]; branchId: number; branchName: string }
  | { kind: "shipping"; ids: number[] }
  | { kind: "agent"; ids: number[] }
  | null;

const NONE = "none";

export function OrdersWindow() {
  const active = useWindowManager((s) => s.active === "orders");
  const permissions = useSession((s) => s.session?.permissions);
  const canManage = useCan("manage_orders");
  const canReturn = useCan("return_orders");
  const canPrint = useCan("print_pos_invoice");
  const canPay = useCan("pay_orders");
  const canDelete = useCan("delete_orders");
  const online = useConnection((s) => s.status === "online");

  const [tab, setTab] = useState<OrderTab>("all");
  const [searchText, setSearchText] = useState("");
  const [draft, setDraft] = useState<FilterDraft>(EMPTY_DRAFT);
  const [applied, setApplied] = useState<FilterDraft>(EMPTY_DRAFT);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [detailsId, setDetailsId] = useState<number | null>(null);
  const requestedInvoice = useOrderNavigation((state) => state.invoiceId);
  useEffect(() => {
    if (!active || requestedInvoice === null) return;
    setDetailsId(requestedInvoice);
    useOrderNavigation.getState().clear();
  }, [active, requestedInvoice]);
  const [pending, setPending] = useState<Pending>(null);
  const [payId, setPayId] = useState<number | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [cancelId, setCancelId] = useState<number | null>(null);
  const [ship, setShip] = useState<OrderScan | null>(null);
  const scanAction = useOrderPreferences((s) => s.scanAction);
  const [dispatch, setDispatch] = useState<{ mode: DispatchMode; ids: number[] } | null>(null);
  const search = useDebouncedValue(searchText, 300);
  const selection = useSelection();
  const { clear: clearSelection } = selection;

  const filters = useMemo<OrderFilters>(() => ({ search, ...draftToFilters(applied) }), [search, applied]);
  const query = useMemo(() => ({ ...filters, tab, page, pageSize }), [filters, tab, page, pageSize]);
  const list = useOrdersList(query, active);
  const counts = useOrderCounts(filters, active);
  const lookups = useOrderLookups();
  const changeStatus = useChangeOrderStatus();
  const returnOrders = useReturnOrders();
  const assign = useAssignOrders();
  const cancelOrder = useCancelOrder();

  // Scanning an order's barcode (Settings → الطلبات): shipping-barcode dialog, details, or nothing.
  // An order already in the table opens with no round trip; others are looked up by FINORA.
  const rows = list.data?.rows;
  useBarcodeScanner(
    useCallback(
      (code: string) => {
        const row = rows?.find((r) => String(r.id) === code) ?? null;
        if (scanAction === "select") {
          const pick = (id: number) => {
            selection.setMany([id], true);
            toast.success(`حُدد الطلب #${id}`);
          };
          if (row) pick(row.id);
          else
            finora.orders
              .findByBarcode(code)
              .then(pick)
              .catch((error: unknown) => toast.error(orderFailureMessage(error)));
          return;
        }
        if (scanAction === "shipping" && canManage && online) {
          setShip({ code, orderId: row?.id ?? null, row });
          return;
        }
        if (row) {
          setDetailsId(row.id);
          return;
        }
        finora.orders
          .findByBarcode(code)
          .then((id) => setDetailsId(id))
          .catch((error: unknown) => toast.error(orderFailureMessage(error)));
      },
      [rows, scanAction, canManage, online, selection],
    ),
    active &&
      scanAction !== "off" &&
      payId === null &&
      ship === null &&
      cancelId === null &&
      editId === null &&
      dispatch === null,
    3,
  );

  const resetPaging = useCallback(() => {
    setPage(1);
    clearSelection();
  }, [clearSelection]);

  const visibleTabs = useMemo<TabItem<OrderTab>[]>(
    () =>
      ORDER_TABS.filter((id) => {
        if (id === "all") return true;
        const needed = ORDER_TAB_PERMISSIONS[id];
        return permissions?.includes(needed) ?? false;
      }).map((id) => ({ id, label: ORDER_TAB_LABELS[id], count: counts.data?.[id] })),
    [counts.data, permissions],
  );

  const activeFilterCount = Object.values(applied).filter(Boolean).length;
  const busy = changeStatus.isPending || returnOrders.isPending || assign.isPending;

  const print = useCallback((ids: number[]) => {
    finora.orders.print(ids).catch((error: unknown) => toast.error(toFinoraError(error).message));
  }, []);

  const rowMenu = useCallback(
    (row: OrderRow) => {
      const items: MenuItem[] = [
        { id: "details", label: "عرض التفاصيل", icon: Eye, onSelect: () => setDetailsId(row.id) },
        ...(canPay && row.can_pay
          ? [
              {
                id: "pay",
                label: "تسديد",
                icon: Banknote,
                disabled: !online,
                onSelect: () => setPayId(row.id),
              },
            ]
          : []),
        ...(canManage
          ? [
              {
                id: "edit",
                label: "تعديل سريع",
                icon: Pencil,
                disabled: !online || row.is_stock_locked,
                onSelect: () => setEditId(row.id),
              },
            ]
          : []),
      ];
      if (canManage) {
        items.push(
          {
            id: "status",
            label: "تغيير الحالة",
            icon: RefreshCcw,
            disabled: !online,
            onSelect: () => setPending({ kind: "status", ids: [row.id] }),
          },
          {
            id: "agent",
            label: "تعيين مندوب",
            icon: UserRound,
            disabled: !online,
            onSelect: () => setPending({ kind: "agent", ids: [row.id] }),
          },
          {
            id: "shipping",
            label: "تغيير شركة النقل",
            icon: Truck,
            disabled: !online,
            onSelect: () => setPending({ kind: "shipping", ids: [row.id] }),
          },
          {
            id: "shipping-barcode",
            label: "رقم وصل شركة النقل",
            icon: ScanBarcode,
            disabled: !online || row.is_stock_locked,
            onSelect: () => setShip({ code: String(row.id), orderId: row.id, row, receiptMode: true }),
          },
        );
      }
      if (canPrint)
        items.push({ id: "print", label: "طباعة", icon: Printer, onSelect: () => print([row.id]) });
      if (canReturn && canReturnOrder(row))
        items.push({
          id: "return",
          label: "إرجاع الطلب",
          icon: Undo2,
          disabled: !online || busy,
          onSelect: () => setPending({ kind: "return", ids: [row.id] }),
        });
      if (canDelete && row.can_cancel)
        items.push({
          id: "cancel",
          label: "إلغاء الطلب",
          icon: Ban,
          disabled: !online,
          onSelect: () => setCancelId(row.id),
        });
      return (
        <Menu
          label={`إجراءات الطلب ${row.id}`}
          items={items}
          trigger={(props) => (
            <button
              {...props}
              type="button"
              aria-label={`إجراءات الطلب ${row.id}`}
              className="grid h-9 w-9 place-items-center rounded-[10px] bg-white text-ink-soft shadow-control ring-1 ring-line/70 transition-colors hover:text-violet-deep"
            >
              <MoreHorizontal size={17} />
            </button>
          )}
        />
      );
    },
    [canManage, canPrint, canPay, canDelete, canReturn, busy, online, print],
  );

  const columns = useMemo<Column<OrderRow>[]>(
    () => [
      {
        id: "id",
        header: "رقم الطلب",
        width: "110px",
        cell: (row) => (
          <div className="min-w-0">
            <span className="ltr-isolate text-[15px] font-bold text-ink">#{row.id}</span>
            {row.shipping_barcode && (
              <p
                className="ltr-isolate mt-1 truncate text-[11px] text-violet-deep"
                title={`وصل شركة النقل: ${row.shipping_barcode}`}
              >
                {row.shipping_barcode}
              </p>
            )}
          </div>
        ),
      },
      {
        id: "customer",
        header: "العميل",
        width: "20%",
        cell: (row) => (
          <div className="min-w-0 leading-tight">
            <p className="truncate font-semibold">{row.customer_name || "—"}</p>
            <p className="ltr-isolate mt-1 truncate text-xs text-ink-soft">{row.phone}</p>
          </div>
        ),
      },
      { id: "city", header: "المحافظة", width: "10%", cell: (row) => row.city || "—" },
      {
        id: "address",
        header: "العنوان",
        minTableWidth: 1050,
        cell: (row) => <span className="line-clamp-2 text-ink-soft">{row.address || "—"}</span>,
      },
      {
        id: "agent",
        header: "المندوب",
        width: "13%",
        minTableWidth: 980,
        cell: (row) =>
          row.delivery_agent ? (
            <span className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-violet-soft/70 px-2.5 py-1 text-[12.5px] font-medium text-violet-deep">
              <UserRound size={13} className="shrink-0" aria-hidden />
              <span className="truncate">{row.delivery_agent}</span>
            </span>
          ) : (
            <span className="text-xs text-ink-faint">غير معيّن</span>
          ),
      },
      {
        id: "date",
        header: "التاريخ",
        width: "112px",
        cell: (row) => <span className="ltr-isolate text-ink-soft">{formatOrderDate(row.date)}</span>,
      },
      {
        id: "total",
        header: "المبلغ",
        width: "140px",
        cell: (row) => <span className="ltr-isolate font-semibold">{formatIqd(row.total)}</span>,
      },
      {
        id: "payment",
        header: "الدفع",
        width: "150px",
        cell: (row) => {
          const due = collectionDue(row.total, row.paid_amount, row.payment_status);
          const paid = row.payment_status.trim() === "مسدد";
          if (canPay && row.can_pay)
            return (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setPayId(row.id);
                }}
                disabled={!online}
                aria-label={`تسديد الطلب ${row.id}`}
                className="group inline-flex h-8 items-center gap-1.5 rounded-full bg-success-soft px-3 text-[12.5px] font-semibold text-success ring-1 ring-success/20 transition-colors hover:bg-success hover:text-white disabled:opacity-50"
              >
                <Banknote size={14} aria-hidden />
                تسديد
                {row.payment_status.trim() === "جزئي" && (
                  <span className="ltr-isolate text-[11px] font-medium opacity-80">{formatIqd(due)}</span>
                )}
              </button>
            );
          return (
            <span
              className={paid ? "text-[12.5px] font-semibold text-success" : "text-[12.5px] text-ink-faint"}
            >
              {row.payment_status || "—"}
            </span>
          );
        },
      },
      {
        id: "status",
        header: "الحالة",
        width: "130px",
        align: "center",
        cell: (row) => <StatusBadge {...orderStatusStyle(row.status)} />,
      },
    ],
    [canPay, online],
  );

  const ids = selection.ids;
  const runStatus = (targetIds: number[], status: string) => {
    if (status === RETURN_TARGET.value) {
      setPending({ kind: "return", ids: targetIds });
    } else if (targetIds.length > 1) {
      setPending({ kind: "confirm-status", ids: targetIds, status });
    } else {
      setPending(null);
      changeStatus.mutate({ ids: targetIds, status }, { onSuccess: clearSelection });
    }
  };

  const statusOptions: PickerOption[] = [
    ...STATUS_TARGETS.map((s) => ({ value: s.value, label: s.label })),
    ...(canReturn ? [{ value: RETURN_TARGET.value, label: RETURN_TARGET.label }] : []),
  ];
  const lookupOptions = (kind: "shipping" | "agent"): PickerOption[] => [
    { value: NONE, label: kind === "shipping" ? "بدون شركة نقل" : "بدون مندوب" },
    ...((kind === "shipping" ? lookups.data?.shipping_companies : lookups.data?.delivery_agents) ?? []).map(
      (o) => ({
        value: String(o.id),
        label: o.name,
      }),
    ),
  ];

  const bulkItems: MenuItem[] = [
    ...(canManage
      ? [
          {
            id: "status",
            label: "تغيير الحالة",
            icon: RefreshCcw,
            onSelect: () => setPending({ kind: "status", ids }),
          },
          {
            id: "agent",
            label: "تغيير المندوب",
            icon: UserRound,
            onSelect: () => setPending({ kind: "agent", ids }),
          },
          {
            id: "shipping",
            label: "تغيير شركة النقل",
            icon: Truck,
            onSelect: () => setPending({ kind: "shipping", ids }),
          },
          {
            id: "agent-report",
            label: "كشف مندوب (يظهر في بوابته)",
            icon: FileText,
            onSelect: () => setDispatch({ mode: "agent_report", ids }),
          },
          {
            id: "handover",
            label: "كشف تسليم لشركة نقل",
            icon: Send,
            onSelect: () => setDispatch({ mode: "handover", ids }),
          },
        ]
      : []),
    ...(canReturn
      ? [{ id: "return", label: "ترجيع", icon: Undo2, onSelect: () => setPending({ kind: "return", ids }) }]
      : []),
  ];

  return (
    <div className="relative flex h-full flex-col gap-3">
      <div className="flex items-center gap-3">
        <FilterPanel
          activeCount={activeFilterCount}
          onApply={() => {
            setApplied(draft);
            resetPaging();
          }}
          onClear={() => {
            setDraft(EMPTY_DRAFT);
            setApplied(EMPTY_DRAFT);
            resetPaging();
          }}
        >
          <Field label="المحافظة">
            <SelectInput
              value={draft.city}
              onChange={(city) => setDraft({ ...draft, city })}
              placeholder="كل المحافظات"
              options={(lookups.data?.cities ?? []).map((c) => ({ value: c, label: c }))}
            />
          </Field>
          <Field label="شركة النقل">
            <SelectInput
              value={draft.shipping}
              onChange={(shipping) => setDraft({ ...draft, shipping })}
              placeholder="الكل"
              options={(lookups.data?.shipping_companies ?? []).map((c) => ({
                value: c.name,
                label: c.name,
              }))}
            />
          </Field>
          <Field label="المندوب" wide>
            <SelectInput
              value={draft.agent}
              onChange={(agent) => setDraft({ ...draft, agent })}
              placeholder="الكل"
              options={[
                { value: "none", label: "بدون مندوب" },
                ...(lookups.data?.delivery_agents ?? []).map((a) => ({ value: a.name, label: a.name })),
              ]}
            />
          </Field>
          <Field label="من تاريخ">
            <DateInput value={draft.dateFrom} onChange={(dateFrom) => setDraft({ ...draft, dateFrom })} />
          </Field>
          <Field label="إلى تاريخ">
            <DateInput value={draft.dateTo} onChange={(dateTo) => setDraft({ ...draft, dateTo })} />
          </Field>
          <Field label="أقل مبلغ">
            <NumberInput
              value={draft.amountMin}
              onChange={(amountMin) => setDraft({ ...draft, amountMin })}
              placeholder="0"
            />
          </Field>
          <Field label="أعلى مبلغ">
            <NumberInput
              value={draft.amountMax}
              onChange={(amountMax) => setDraft({ ...draft, amountMax })}
            />
          </Field>
        </FilterPanel>

        <SearchBox
          className="flex-1"
          value={searchText}
          onChange={(value) => {
            setSearchText(value);
            resetPaging();
          }}
          busy={list.isFetching && search !== "" && searchText === search}
          placeholder="بحث برقم الطلب، اسم العميل، رقم الهاتف، المحافظة أو العنوان…"
        />

        <button
          type="button"
          aria-pressed={scanAction === "select"}
          title="عند التفعيل: مسح باركود الطلب يحدده مباشرة في الجدول"
          onClick={() =>
            useOrderPreferences
              .getState()
              .update({ scanAction: scanAction === "select" ? "shipping" : "select" })
          }
          className={cn(
            "flex h-11 items-center gap-2 rounded-control border px-4 text-sm shadow-control",
            scanAction === "select"
              ? "border-maroon/30 bg-maroon-soft font-semibold text-maroon"
              : "border-line bg-white/85 text-ink-soft",
          )}
        >
          <ListChecks size={17} aria-hidden />
          مسح للتحديد
        </button>
        {canManage && (
          <button
            type="button"
            disabled={!online}
            onClick={() => setDispatch({ mode: "agent_report", ids })}
            className="flex h-11 items-center gap-2 rounded-control border border-line bg-white/85 px-4 text-sm text-ink shadow-control disabled:opacity-40"
          >
            <Send size={16} aria-hidden />
            تسليم وإسناد
            {ids.length > 0 && (
              <span className="ltr-isolate rounded-full bg-maroon-soft px-1.5 text-xs text-maroon">
                {ids.length}
              </span>
            )}
          </button>
        )}
        {canPrint && (
          <button
            type="button"
            disabled={ids.length === 0}
            onClick={() => print(ids)}
            className="flex h-11 items-center gap-2 rounded-control bg-gradient-to-l from-maroon to-[#9b2c55] px-5 text-sm font-semibold text-white shadow-control transition-opacity disabled:opacity-40"
          >
            <Printer size={17} aria-hidden />
            طباعة المحدد
            {ids.length > 0 && (
              <span className="ltr-isolate rounded-full bg-white/20 px-1.5 text-xs">{ids.length}</span>
            )}
          </button>
        )}
        {bulkItems.length > 0 && (
          <Menu
            label="إجراءات جماعية"
            items={bulkItems.map((item) => ({ ...item, disabled: !online }))}
            trigger={(props) => (
              <button
                {...props}
                type="button"
                disabled={ids.length === 0}
                className="flex h-11 items-center gap-2 rounded-control border border-line bg-white/85 px-4 text-sm text-ink shadow-control disabled:opacity-40"
              >
                إجراءات
                <ChevronDown size={15} aria-hidden />
              </button>
            )}
          />
        )}
      </div>

      <StatusTabs
        label="حالات الطلبات"
        tabs={visibleTabs}
        value={tab}
        onChange={(next) => {
          setTab(next);
          resetPaging();
        }}
      />

      <DataTable
        label="جدول الطلبات"
        columns={columns}
        rows={list.data?.rows}
        loading={list.isLoading}
        fetching={list.isFetching}
        error={list.error ? toFinoraError(list.error).message : null}
        onRetry={() => void list.refetch()}
        emptyTitle={search || activeFilterCount ? "لا توجد طلبات مطابقة" : "لا توجد طلبات في هذا القسم"}
        emptyHint={search || activeFilterCount ? "جرّب تعديل البحث أو مسح التصفية." : undefined}
        selection={selection}
        activeId={detailsId}
        onOpen={(row) => setDetailsId(row.id)}
        rowActions={rowMenu}
      />

      {list.data && (
        <TablePagination
          page={list.data.page}
          totalPages={list.data.total_pages}
          total={list.data.total}
          pageSize={pageSize}
          noun="طلب"
          onPage={(next) => {
            setPage(next);
            clearSelection();
          }}
          onPageSize={(size) => {
            setPageSize(size);
            resetPaging();
          }}
        />
      )}

      {dispatch && (
        <DispatchDialog
          carriers={lookups.data?.shipping_companies ?? []}
          agents={lookups.data?.delivery_agents ?? []}
          initialIds={dispatch.ids}
          initialMode={dispatch.mode}
          onClose={() => setDispatch(null)}
        />
      )}

      <OrderDetailsPanel
        orderId={detailsId}
        row={list.data?.rows.find((r) => r.id === detailsId) ?? null}
        canAssign={canManage && online}
        canPay={canPay && online}
        canCancel={canDelete && online}
        canPrint={canPrint}
        canEdit={canManage && online}
        canReturn={canReturn && online && !busy}
        onReturn={(id) => setPending({ kind: "return", ids: [id] })}
        onShippingReceipt={(id) =>
          setShip({
            code: String(id),
            orderId: id,
            row: list.data?.rows.find((r) => r.id === id) ?? null,
            receiptMode: true,
          })
        }
        onEdit={setEditId}
        onAssignAgent={(id) => setPending({ kind: "agent", ids: [id] })}
        onAssignShipping={(id) => setPending({ kind: "shipping", ids: [id] })}
        onPay={setPayId}
        onCancel={setCancelId}
        onPrint={(id) => print([id])}
        onClose={() => setDetailsId(null)}
      />

      <PaymentDialog orderId={payId} onClose={() => setPayId(null)} />
      {editId !== null && <QuickOrderEditor orderId={editId} onClose={() => setEditId(null)} />}
      <ShippingBarcodeDialog
        scan={ship}
        onClose={() => setShip(null)}
        onShowDetails={(id) => {
          setShip(null);
          setDetailsId(id);
        }}
      />
      <ConfirmDialog
        open={cancelId !== null}
        title={`إلغاء الطلب #${cancelId ?? ""}`}
        message="سيُلغى الطلب ويعيد FINORA المخزون ويعكس أي دفعات مسجلة عليه. لا يمكن التراجع من التطبيق."
        confirmLabel="إلغاء الطلب"
        tone="danger"
        busy={cancelOrder.isPending}
        onConfirm={() => {
          if (cancelId === null) return;
          const id = cancelId;
          cancelOrder.mutate(id, { onSettled: () => setCancelId(null) });
        }}
        onClose={() => setCancelId(null)}
      />

      <PickerDialog
        open={pending?.kind === "status"}
        title={
          pending && pending.ids.length > 1 ? `تغيير حالة ${pending.ids.length} طلبات` : "تغيير حالة الطلب"
        }
        options={statusOptions}
        confirmLabel="متابعة"
        busy={busy}
        onConfirm={(status) => pending && runStatus(pending.ids, status)}
        onClose={() => setPending(null)}
      />
      <ConfirmDialog
        open={pending?.kind === "confirm-status"}
        title="تأكيد تغيير الحالة"
        message={
          pending?.kind === "confirm-status"
            ? `سيتم تغيير حالة ${pending.ids.length} طلبات إلى "${orderStatusStyle(pending.status).label}". يطبّق FINORA قواعد المخزون على كل طلب.`
            : ""
        }
        confirmLabel="تغيير الحالة"
        busy={busy}
        onConfirm={() => {
          if (pending?.kind !== "confirm-status") return;
          const { ids: targetIds, status } = pending;
          setPending(null);
          changeStatus.mutate({ ids: targetIds, status }, { onSuccess: clearSelection });
        }}
        onClose={() => setPending(null)}
      />
      <PickerDialog
        open={pending?.kind === "return"}
        title="إرجاع الطلبات"
        description="اختر الفرع الذي استلم القطع فعلياً. الإرجاع كامل للطلب؛ ستراجع العملية قبل تنفيذها. الطلب غير المشحون بحالة «تم الطلب» يستخدم الإلغاء."
        options={(lookups.data?.branches ?? []).map((b) => ({ value: String(b.id), label: b.name }))}
        confirmLabel="مراجعة الإرجاع"
        busy={busy}
        onConfirm={(branch) => {
          if (!pending) return;
          const targetIds = pending.ids;
          setPending({
            kind: "confirm-return",
            ids: targetIds,
            branchId: Number(branch),
            branchName: lookups.data?.branches.find((b) => b.id === Number(branch))?.name ?? branch,
          });
        }}
        onClose={() => setPending(null)}
      />
      <ConfirmDialog
        open={pending?.kind === "confirm-return"}
        title="تأكيد إرجاع الطلب"
        message={
          pending?.kind === "confirm-return"
            ? `إرجاع كامل للطلبات ${pending.ids.map((id) => `#${id}`).join("، ")} إلى «${pending.branchName}». تأكد من استلام القطع فعلياً. يعيد FINORA المخزون مرة واحدة، ويعكس الدفعات المسجلة ويلغي الدين والأقساط المرتبطة وفق قواعد الحسابات؛ وتظهر العملية بالسجل. لا يمكن التراجع من هذه الشاشة.`
            : ""
        }
        confirmLabel="تأكيد الإرجاع"
        tone="danger"
        busy={busy}
        onConfirm={() => {
          if (pending?.kind !== "confirm-return") return;
          returnOrders.mutate(
            { ids: pending.ids, branchId: pending.branchId },
            {
              onSuccess: () => {
                setPending(null);
                clearSelection();
              },
            },
          );
        }}
        onClose={() => {
          if (!busy) setPending(null);
        }}
      />
      {(["shipping", "agent"] as const).map((kind) => (
        <PickerDialog
          key={kind}
          open={pending?.kind === kind}
          title={kind === "shipping" ? "تغيير شركة النقل" : "تعيين مندوب"}
          options={lookupOptions(kind)}
          confirmLabel="حفظ"
          busy={busy}
          onConfirm={(value) => {
            if (!pending) return;
            const targetIds = pending.ids;
            setPending(null);
            assign.mutate(
              { kind, ids: targetIds, targetId: value === NONE ? null : Number(value) },
              { onSuccess: clearSelection },
            );
          }}
          onClose={() => setPending(null)}
        />
      ))}
    </div>
  );
}
