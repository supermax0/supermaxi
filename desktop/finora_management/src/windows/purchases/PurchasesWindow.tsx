import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PackagePlus,
  Clock,
  Eye,
  FilePen,
  FileText,
  MoreHorizontal,
  Package,
  Printer,
  Wallet,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import {
  PURCHASE_TABS,
  type PurchaseRow,
  type PurchasesQuery,
  type PurchaseTab,
} from "@/api/finora/purchases";
import { DataTable, type Column } from "@/components/DataTable";
import { ConfirmDialog } from "@/components/Dialog";
import { DateInput, Field, FilterPanel, SelectInput } from "@/components/FilterPanel";
import { Menu, type MenuItem } from "@/components/Menu";
import { SearchBox } from "@/components/SearchBox";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { StatusTabs } from "@/components/StatusTabs";
import { TablePagination } from "@/components/TablePagination";
import { PURCHASE_TAB_STYLES } from "@/features/purchases/status";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { canMutate, useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
import { formatIqd } from "@/utils/money";
import { useComposer } from "@/features/purchases/composer";
import { useWindowManager } from "@/stores/windowManager";
import { usePurchaseNavigation, purchaseNavigationScope } from "@/stores/purchaseNavigation";
import { PurchaseComposer } from "./PurchaseComposer";
import { PurchaseDetailsPanel } from "./PurchaseDetailsPanel";

const TAB_LABELS: Record<PurchaseTab, string> = {
  all: "الكل",
  draft: "مسودات",
  confirmed: "مستلمة ومسددة",
  unpaid: "بانتظار الدفع",
  cancelled: "ملغية",
};

interface Draft {
  supplierId: string;
  dateFrom: string;
  dateTo: string;
}
const EMPTY: Draft = { supplierId: "", dateFrom: "", dateTo: "" };

export function PurchasesWindow() {
  const online = useConnection((s) => s.status === "online");
  const active = useWindowManager((s) => s.active === "purchases");
  const hasDraft = useComposer((s) => s.lines.length > 0 || s.supplier !== null);
  const composerOpen = useComposer((s) => s.open);
  const openComposer = useCallback(() => useComposer.getState().setOpen(true), []);

  // Ctrl+N: new purchase while this window is open.
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.code === "KeyN") {
        event.preventDefault();
        openComposer();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, openComposer]);
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<PurchaseTab>("all");
  const [searchText, setSearchText] = useState("");
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [applied, setApplied] = useState<Draft>(EMPTY);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [detailsId, setDetailsId] = useState<number | null>(null);
  const requestedPurchase = usePurchaseNavigation((state) => state.target);
  const [sourceTarget, setSourceTarget] = useState<typeof requestedPurchase>(null);
  const currentScope = purchaseNavigationScope();
  useEffect(() => {
    if (!active || composerOpen || requestedPurchase === null) return;
    setSourceTarget(requestedPurchase);
    setDetailsId(requestedPurchase.id);
    usePurchaseNavigation.getState().clear();
  }, [active, composerOpen, requestedPurchase]);
  const sourceDetails = useQuery({
    queryKey: ["purchases", "source", currentScope, sourceTarget?.id],
    queryFn: () => {
      if (!sourceTarget || sourceTarget.scope !== currentScope) throw Error("سياق فاتورة الشراء تغيّر");
      return finora.purchases.details(sourceTarget.id);
    },
    enabled:
      active && sourceTarget !== null && sourceTarget.scope === currentScope && sourceTarget.id === detailsId,
  });
  const [cancelTarget, setCancelTarget] = useState<PurchaseRow | null>(null);
  const search = useDebouncedValue(searchText, 300);

  const query = useMemo<PurchasesQuery>(
    () => ({
      tab,
      page,
      pageSize,
      search,
      supplierId: applied.supplierId ? Number(applied.supplierId) : undefined,
      dateFrom: applied.dateFrom || undefined,
      dateTo: applied.dateTo || undefined,
    }),
    [tab, page, pageSize, search, applied],
  );
  const list = useQuery({
    queryKey: ["purchases", "page", query],
    queryFn: () => finora.purchases.list(query),
  });

  const cancel = useMutation({
    mutationFn: (row: PurchaseRow) => {
      if (!canMutate()) throw new Error("offline");
      return finora.purchases.cancel(row.id);
    },
    onSuccess: (result, row) => toast.success(result.message ?? `تم إلغاء ${row.invoice_no}.`),
    onError: (error) =>
      toast.error(
        error instanceof Error && error.message === "offline"
          ? "لا يمكن التعديل بدون اتصال بـ FINORA."
          : toFinoraError(error).message,
      ),
    onSettled: () => {
      setCancelTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["purchases"] });
      // FINORA reverses the purchase's stock.
      void queryClient.invalidateQueries({ queryKey: ["products"] });
    },
  });

  const print = useCallback((id: number) => {
    finora.purchases.print(id).catch((error: unknown) => toast.error(toFinoraError(error).message));
  }, []);

  const rowMenu = useCallback(
    (row: PurchaseRow) => {
      const items: MenuItem[] = [
        { id: "details", label: "عرض التفاصيل", icon: Eye, onSelect: () => setDetailsId(row.id) },
        {
          id: "edit",
          label: "تعديل في FINORA",
          icon: FilePen,
          disabled: row.tab === "cancelled",
          onSelect: () => {
            finora.purchases
              .openEditor(row.id)
              .catch((error: unknown) => toast.error(toFinoraError(error).message));
          },
        },
        { id: "print", label: "طباعة", icon: Printer, onSelect: () => print(row.id) },
      ];
      if (row.tab !== "cancelled") {
        items.push({
          id: "cancel",
          label: "إلغاء",
          icon: XCircle,
          danger: true,
          disabled: !online,
          onSelect: () => setCancelTarget(row),
        });
      }
      return (
        <Menu
          label={`إجراءات ${row.invoice_no}`}
          items={items}
          trigger={(props) => (
            <button
              {...props}
              type="button"
              aria-label={`إجراءات ${row.invoice_no}`}
              className="grid h-9 w-9 place-items-center rounded-[10px] bg-white text-ink-soft shadow-control ring-1 ring-line/70 hover:text-violet-deep"
            >
              <MoreHorizontal size={17} />
            </button>
          )}
        />
      );
    },
    [online, print],
  );

  const columns = useMemo<Column<PurchaseRow>[]>(
    () => [
      {
        id: "no",
        header: "رقم طلب الشراء",
        width: "150px",
        cell: (row) => <span className="ltr-isolate font-bold">{row.invoice_no}</span>,
      },
      {
        id: "supplier",
        header: "المورد",
        width: "20%",
        cell: (row) => <span className="font-semibold">{row.supplier || "—"}</span>,
      },
      {
        id: "date",
        header: "التاريخ",
        width: "112px",
        cell: (row) => <span className="ltr-isolate text-ink-soft">{row.date}</span>,
      },
      {
        id: "items",
        header: "عدد الأصناف",
        width: "100px",
        align: "center",
        cell: (row) => <span className="ltr-isolate">{formatNumber(row.item_count)}</span>,
      },
      {
        id: "total",
        header: "المبلغ الإجمالي",
        width: "150px",
        cell: (row) => <span className="ltr-isolate font-semibold">{formatIqd(row.grand_total)}</span>,
      },
      {
        id: "remaining",
        header: "المتبقي",
        width: "130px",
        minTableWidth: 1050,
        cell: (row) => (
          <span className={`ltr-isolate ${row.remaining_total > 0 ? "text-warning" : "text-ink-faint"}`}>
            {formatIqd(row.remaining_total)}
          </span>
        ),
      },
      {
        id: "status",
        header: "الحالة",
        width: "130px",
        align: "center",
        cell: (row) => <StatusBadge {...PURCHASE_TAB_STYLES[row.tab]} />,
      },
      {
        id: "notes",
        header: "الملاحظات",
        minTableWidth: 1150,
        cell: (row) => (
          <span className="line-clamp-1 text-ink-soft">{row.notes || row.first_product || "—"}</span>
        ),
      },
    ],
    [],
  );

  const summary = list.data?.summary;
  const counts = list.data?.counts;
  const activeFilters = Object.values(applied).filter(Boolean).length;
  const selected =
    list.data?.rows.find((row) => row.id === detailsId) ??
    (sourceTarget?.scope === currentScope && sourceTarget.id === detailsId
      ? (sourceDetails.data ?? null)
      : null);

  return (
    <div className="relative flex h-full flex-col gap-3">
      <div className="grid grid-cols-4 gap-3">
        <StatCard
          label="إجمالي المشتريات"
          value={formatNumber(summary?.total_amount ?? 0)}
          unit="د.ع"
          icon={FileText}
          tone="azure"
          loading={!summary}
        />
        <StatCard
          label="عدد الطلبات"
          value={formatNumber(summary?.count ?? 0)}
          icon={Package}
          tone="success"
          loading={!summary}
        />
        <StatCard
          label="مسودات"
          value={formatNumber(summary?.draft ?? 0)}
          unit="طلب"
          icon={Clock}
          tone="warning"
          loading={!summary}
          active={tab === "draft"}
          onClick={() => {
            setTab("draft");
            setPage(1);
          }}
        />
        <StatCard
          label="بانتظار الدفع"
          value={formatNumber(summary?.unpaid ?? 0)}
          unit="طلب"
          icon={Wallet}
          tone="violet"
          loading={!summary}
          active={tab === "unpaid"}
          onClick={() => {
            setTab("unpaid");
            setPage(1);
          }}
        />
      </div>

      <div className="flex items-center gap-3">
        <StatusTabs
          label="حالات المشتريات"
          value={tab}
          onChange={(next) => {
            setTab(next);
            setPage(1);
          }}
          tabs={PURCHASE_TABS.map((id) => ({ id, label: TAB_LABELS[id], count: counts?.[id] }))}
        />
        <FilterPanel
          activeCount={activeFilters}
          onApply={() => {
            setApplied(draft);
            setPage(1);
          }}
          onClear={() => {
            setDraft(EMPTY);
            setApplied(EMPTY);
            setPage(1);
          }}
        >
          <Field label="المورد" wide>
            <SelectInput
              value={draft.supplierId}
              onChange={(supplierId) => setDraft({ ...draft, supplierId })}
              placeholder="كل الموردين"
              options={(list.data?.suppliers ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
            />
          </Field>
          <Field label="من تاريخ">
            <DateInput value={draft.dateFrom} onChange={(dateFrom) => setDraft({ ...draft, dateFrom })} />
          </Field>
          <Field label="إلى تاريخ">
            <DateInput value={draft.dateTo} onChange={(dateTo) => setDraft({ ...draft, dateTo })} />
          </Field>
        </FilterPanel>
        <SearchBox
          className="flex-1"
          value={searchText}
          onChange={(value) => {
            setSearchText(value);
            setPage(1);
          }}
          busy={list.isFetching && search !== "" && searchText === search}
          placeholder="بحث برقم الطلب، اسم المورد، رقم الفاتورة…"
        />
        <button
          type="button"
          onClick={openComposer}
          title="Ctrl+N"
          className="relative flex h-11 shrink-0 items-center gap-2 rounded-control bg-gradient-to-l from-azure to-violet-deep px-5 text-sm font-bold text-white shadow-float transition-[transform,opacity] hover:opacity-95 active:scale-[0.98]"
        >
          <PackagePlus size={18} aria-hidden />
          {hasDraft ? "متابعة فاتورة الشراء" : "فاتورة شراء جديدة"}
          {hasDraft && !composerOpen && (
            <span
              className="absolute -end-1 -top-1 h-3 w-3 rounded-full bg-warning ring-2 ring-white"
              aria-label="مسودة غير محفوظة"
            />
          )}
        </button>
      </div>

      <DataTable
        label="جدول المشتريات"
        columns={columns}
        rows={list.data?.rows}
        loading={list.isLoading}
        fetching={list.isFetching}
        error={list.error ? toFinoraError(list.error).message : null}
        onRetry={() => void list.refetch()}
        emptyTitle={search || activeFilters ? "لا توجد مشتريات مطابقة" : "لا توجد مشتريات في هذا القسم"}
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
          noun="طلب شراء"
          onPage={setPage}
          onPageSize={(size) => {
            setPageSize(size);
            setPage(1);
          }}
        />
      )}

      <PurchaseDetailsPanel purchase={selected} onClose={() => setDetailsId(null)} />
      {requestedPurchase && composerOpen && (
        <p role="status" className="rounded-control bg-violet-soft p-3 text-sm text-violet">
          عندك إدخال مشتريات مفتوح؛ أغلقه بعد الحفظ حتى ينفتح المستند المطلوب.
        </p>
      )}
      {sourceDetails.error && sourceTarget?.id === detailsId && (
        <p role="alert" className="rounded-control border border-danger/20 p-3 text-sm text-danger">
          {toFinoraError(sourceDetails.error).message}
          <button type="button" onClick={() => void sourceDetails.refetch()} className="ms-3 underline">
            إعادة المحاولة
          </button>
        </p>
      )}
      <PurchaseComposer suppliers={list.data?.suppliers ?? []} active={active} />

      <ConfirmDialog
        open={cancelTarget !== null}
        title="إلغاء طلب الشراء"
        tone="danger"
        message={
          cancelTarget
            ? `سيتم إلغاء ${cancelTarget.invoice_no} من ${cancelTarget.supplier}. يعكس FINORA أثره على المخزون والدفعات.`
            : ""
        }
        confirmLabel="إلغاء الطلب"
        busy={cancel.isPending}
        onConfirm={() => cancelTarget && cancel.mutate(cancelTarget)}
        onClose={() => setCancelTarget(null)}
      />
    </div>
  );
}
