import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Building2,
  Clock3,
  Download,
  Eye,
  FileText,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  ShoppingBag,
  UsersRound,
  Wallet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import {
  SUPPLIER_TABS,
  type SupplierRow,
  type SupplierTab,
  type SuppliersQuery,
} from "@/api/finora/suppliers";
import { DataTable, type Column } from "@/components/DataTable";
import { ConfirmDialog } from "@/components/Dialog";
import { Field, FilterPanel, NumberInput, SelectInput } from "@/components/FilterPanel";
import { Menu } from "@/components/Menu";
import { SearchBox } from "@/components/SearchBox";
import { StatCard } from "@/components/StatCard";
import { StatusTabs } from "@/components/StatusTabs";
import { TablePagination } from "@/components/TablePagination";
import { useComposer } from "@/features/purchases/composer";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useSelection } from "@/hooks/useSelection";
import { useConnection } from "@/stores/connection";
import { useCan } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { useUi } from "@/stores/ui";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { SupplierDetailsPanel } from "./SupplierDetailsPanel";
import { SupplierEditor, SupplierPaymentDialog, supplierPrimary, supplierSecondary } from "./SupplierDialogs";
import { SupplierSaleDialog } from "./SupplierSaleDialog";
import { useAssistantPageContext } from "@/features/assistant/pageContext";
import { useAssistantDraft, useAssistantDraftFields } from "@/features/assistant/draftQueue";

const LABELS: Record<SupplierTab, string> = {
  all: "الكل",
  debt: "له مستحقات",
  credit: "لنا رصيد",
  settled: "بدون رصيد",
};

function exportPage(rows: SupplierRow[]) {
  const cell = (value: string | number) => {
    const raw = String(value);
    const safe = /^[=+\-@\t\r\n]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  const content = [
    [
      "المورد",
      "الهاتف",
      "هاتف إضافي",
      "العنوان",
      "إجمالي المشتريات",
      "المستحق للمورد",
      "رصيد لنا",
      "آخر تعامل",
    ],
    ...rows.map((s) => [
      s.name,
      s.phone,
      s.phone2,
      s.address,
      s.total_purchases,
      Math.max(s.remaining, 0),
      Math.max(-s.remaining, 0),
      s.last_transaction,
    ]),
  ]
    .map((r) => r.map(cell).join(","))
    .join("\r\n");
  const url = URL.createObjectURL(new Blob(["\ufeff", content], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "FINORA-suppliers.csv";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function SuppliersWindow() {
  const active = useWindowManager((s) => s.active === "suppliers");
  const allowed = useCan("can_manage_suppliers");
  const online = useConnection((s) => s.status === "online");
  const [tab, setTab] = useState<SupplierTab>("all");
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 250);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sort, setSort] = useState<SuppliersQuery["sort"]>("name");
  const [minDraft, setMinDraft] = useState("");
  const [minBalance, setMinBalance] = useState(0);
  const [detailsId, setDetailsId] = useState<number | null>(null);
  const [editor, setEditor] = useState<"create" | SupplierRow | null>(null);
  const [paymentOpen, setPaymentOpen] = useState(false);
  const [saleOpen, setSaleOpen] = useState(false);
  const [replaceDraft, setReplaceDraft] = useState<SupplierRow | null>(null);
  const selection = useSelection();
  const query = useMemo<SuppliersQuery>(
    () => ({ tab, search, page, pageSize, sort, minBalance }),
    [tab, search, page, pageSize, sort, minBalance],
  );
  const list = useQuery({
    queryKey: ["suppliers", "page", query],
    queryFn: () => finora.suppliers.list(query),
    enabled: active && allowed,
  });
  // An assistant draft opens the original form; the form itself consumes and shows the fields.
  const assistantDraft = useAssistantDraft((s) => s.pending);
  useEffect(() => {
    if (!active || !allowed || !assistantDraft) return;
    if (assistantDraft.kind === "supplier") setEditor((current) => current ?? "create");
    if (assistantDraft.kind === "supplier_payment") {
      setDetailsId(Number(assistantDraft.fields.supplier_id));
      setPaymentOpen(true);
    }
  }, [active, allowed, assistantDraft]);
  const [supplierDraft, setSupplierDraft] = useState<Record<string, unknown> | null>(null);
  const [paymentDraft, setPaymentDraft] = useState<Record<string, unknown> | null>(null);
  useAssistantDraftFields("supplier", editor === "create", setSupplierDraft);
  useAssistantDraftFields("supplier_payment", paymentOpen, setPaymentDraft);
  // Each draft fills one form; closing it discards the draft.
  useEffect(() => {
    if (editor === null) setSupplierDraft(null);
    if (!paymentOpen) setPaymentDraft(null);
  }, [editor, paymentOpen]);
  const details = useQuery({
    queryKey: ["suppliers", "details", detailsId],
    queryFn: () => {
      if (detailsId === null) throw new Error("لم يتم اختيار مورد");
      return finora.suppliers.details(detailsId);
    },
    enabled: active && allowed && detailsId !== null,
    placeholderData: undefined,
  });
  useEffect(() => {
    if (!active || detailsId === null) return;
    const onKey = (event: KeyboardEvent) => {
      const ui = useUi.getState();
      if (
        event.key !== "Escape" ||
        ui.paletteOpen ||
        ui.panel !== null ||
        document.querySelector('[aria-modal="true"], [role="menu"]')
      )
        return;
      if (event.target instanceof HTMLInputElement && event.target.type === "search" && event.target.value)
        return;
      event.stopImmediatePropagation();
      setDetailsId(null);
      setPaymentOpen(false);
      setSaleOpen(false);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [active, detailsId]);

  const openDetails = useCallback((s: SupplierRow) => {
    setDetailsId(s.id);
    setPaymentOpen(false);
    setSaleOpen(false);
  }, []);
  const startPurchase = useCallback((s: SupplierRow) => {
    useComposer.getState().reset();
    useComposer.getState().patch({ supplier: { id: s.id, name: s.name } });
    useComposer.getState().setOpen(true);
    useWindowManager.getState().open("purchases");
  }, []);
  const purchase = useCallback(
    (s: SupplierRow) => {
      const draft = useComposer.getState();
      if (draft.supplier?.id === s.id) {
        draft.setOpen(true);
        useWindowManager.getState().open("purchases");
      } else if (draft.lines.length > 0 || draft.supplier) setReplaceDraft(s);
      else startPurchase(s);
    },
    [startPurchase],
  );
  const rowActions = useCallback(
    (s: SupplierRow) => (
      <Menu
        label={`إجراءات ${s.name}`}
        items={[
          { id: "details", label: "عرض التفاصيل", icon: Eye, onSelect: () => openDetails(s) },
          {
            id: "edit",
            label: "تعديل المورد",
            icon: Pencil,
            disabled: !online,
            onSelect: () => setEditor(s),
          },
          {
            id: "purchase",
            label: "إضافة فاتورة شراء",
            icon: Plus,
            disabled: !online,
            onSelect: () => purchase(s),
          },
          {
            id: "statement",
            label: "طباعة كشف الحساب",
            icon: FileText,
            disabled: !online,
            onSelect: () => {
              void finora.suppliers
                .printStatement(s.id)
                .catch((e: unknown) => toast.error(toFinoraError(e).message));
            },
          },
        ]}
        trigger={(props) => (
          <button
            {...props}
            type="button"
            aria-label={`إجراءات ${s.name}`}
            className="grid h-8 w-8 place-items-center rounded-[10px] border border-line/70 bg-white/75 text-ink-soft hover:bg-violet-soft"
          >
            <MoreHorizontal size={17} />
          </button>
        )}
      />
    ),
    [online, openDetails, purchase],
  );
  const columns = useMemo<Column<SupplierRow>[]>(
    () => [
      {
        id: "supplier",
        header: "المورد",
        width: "28%",
        cell: (s) => (
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-gradient-to-br from-violet-soft to-azure-soft text-ink-soft">
              <Building2 size={21} strokeWidth={1.8} />
            </span>
            <div className="min-w-0">
              <p className="truncate font-semibold">{s.name}</p>
              <p className="mt-0.5 max-w-[180px] truncate text-[11px] text-ink-faint">{s.address || "—"}</p>
            </div>
          </div>
        ),
      },
      {
        id: "phone",
        header: "الهاتف",
        minTableWidth: 720,
        width: "16%",
        cell: (s) => <span className="ltr-isolate text-ink-soft">{s.phone || "—"}</span>,
      },
      {
        id: "purchases",
        header: "إجمالي المشتريات",
        width: "18%",
        cell: (s) => <span className="ltr-isolate font-semibold">{formatNumber(s.total_purchases)}</span>,
      },
      {
        id: "remaining",
        header: "الرصيد",
        width: "17%",
        cell: (s) => (
          <span
            className={cn(
              "inline-flex flex-col items-center gap-0.5 rounded-[10px] px-3 py-1.5",
              s.remaining < 0
                ? "bg-violet-soft text-violet-deep"
                : s.remaining > 0
                  ? "bg-danger-soft/70 text-danger"
                  : "bg-success-soft/70 text-success",
            )}
          >
            <span className="ltr-isolate text-[13px] font-semibold">
              {formatNumber(Math.abs(s.remaining))}
            </span>
            {s.remaining !== 0 && (
              <span className="text-[9px]">{s.remaining < 0 ? "لنا عنده" : "مستحق له"}</span>
            )}
          </span>
        ),
      },
      {
        id: "last",
        header: "آخر تعامل",
        minTableWidth: 820,
        width: "14%",
        cell: (s) => <span className="ltr-isolate text-xs text-ink-faint">{s.last_transaction || "—"}</span>,
      },
      {
        id: "open",
        header: "الإجراء",
        width: "80px",
        cell: (s) => (
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[10px] bg-violet-soft/80 px-3 py-2 text-xs font-semibold text-violet-deep hover:bg-violet-soft"
            onClick={(e) => {
              e.stopPropagation();
              openDetails(s);
            }}
          >
            فتح
            <ArrowLeft size={14} />
          </button>
        ),
      },
    ],
    [openDetails],
  );
  const summary = list.data?.summary;
  const shownRows = list.data?.rows ?? [];
  const exportRows =
    selection.selected.size > 0 ? shownRows.filter((s) => selection.selected.has(s.id)) : shownRows;
  const loading = list.isPending;
  const resetPage = () => {
    setPage(1);
    selection.clear();
  };

  useAssistantPageContext("suppliers", {
    tab,
    search: searchText,
    filters: { sort: sort ?? "", minBalance },
    total: list.data?.total,
    ...(detailsId !== null
      ? {
          record: { id: detailsId, name: shownRows.find((s) => s.id === detailsId)?.name ?? `#${detailsId}` },
        }
      : {}),
    checked: {
      count: selection.selected.size,
      names: shownRows.filter((s) => selection.selected.has(s.id)).map((s) => s.name),
    },
  });
  return (
    <div className="supplier-layout relative flex h-full min-h-0 gap-4">
      {detailsId !== null && (
        <SupplierDetailsPanel
          key={detailsId}
          data={details.data}
          loading={details.isPending}
          error={details.error ? toFinoraError(details.error).message : null}
          online={online}
          onClose={() => {
            setDetailsId(null);
            setPaymentOpen(false);
            setSaleOpen(false);
          }}
          onRetry={() => {
            void details.refetch();
          }}
          onEdit={setEditor}
          onPay={() => setPaymentOpen(true)}
          onPurchase={purchase}
          onSell={() => setSaleOpen(true)}
        />
      )}
      <main className="supplier-main flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="mb-5 flex shrink-0 items-center justify-between gap-3">
          <p className="text-[13px] text-ink-soft">
            إجمالي الموردين{" "}
            <span className="ltr-isolate mx-1 font-bold text-maroon">
              {summary ? formatNumber(summary.count) : "—"}
            </span>{" "}
            مورد
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className={supplierSecondary}
              disabled={exportRows.length === 0 || list.isFetching}
              onClick={() => exportPage(exportRows)}
            >
              <Download size={16} />
              {selection.selected.size > 0 ? "تصدير المحدد" : "تصدير الصفحة"}
            </button>
            <Menu
              label="إجراءات الموردين"
              items={[
                {
                  id: "refresh",
                  label: "تحديث الموردين",
                  icon: RefreshCw,
                  disabled: !online,
                  onSelect: () => {
                    void list.refetch();
                    if (detailsId) void details.refetch();
                  },
                },
              ]}
              trigger={(props) => (
                <button
                  {...props}
                  type="button"
                  className={cn(supplierSecondary, "w-11 px-0")}
                  aria-label="إجراءات الموردين"
                >
                  <MoreHorizontal size={19} />
                </button>
              )}
            />
            <button
              type="button"
              className={supplierPrimary}
              disabled={!online || !allowed}
              onClick={() => setEditor("create")}
            >
              <Plus size={17} />
              إضافة مورد
            </button>
          </div>
        </div>
        <div className="supplier-stats mb-5 grid shrink-0 grid-cols-4 gap-3">
          <StatCard
            label="المستحق للموردين"
            value={formatNumber(summary?.payable ?? 0)}
            unit="د.ع"
            icon={Wallet}
            tone="violet"
            loading={loading}
            onClick={() => {
              setTab("debt");
              resetPage();
            }}
          />
          <StatCard
            label="إجمالي المشتريات"
            value={formatNumber(summary?.purchases ?? 0)}
            unit="د.ع"
            icon={ShoppingBag}
            tone="danger"
            loading={loading}
          />
          <StatCard
            label="أرصدة لنا لدى الموردين"
            value={formatNumber(summary?.credit ?? 0)}
            unit="د.ع"
            icon={Wallet}
            tone="success"
            loading={loading}
            onClick={() => {
              setTab("credit");
              resetPage();
            }}
          />
          <StatCard
            label="إجمالي الموردين"
            value={formatNumber(summary?.count ?? 0)}
            icon={UsersRound}
            tone="azure"
            loading={loading}
            onClick={() => {
              setTab("all");
              resetPage();
            }}
          />
        </div>
        <div className="supplier-filters mb-4 flex shrink-0 flex-wrap items-center gap-2">
          <SearchBox
            value={searchText}
            onChange={(v) => {
              setSearchText(v);
              resetPage();
            }}
            busy={list.isFetching}
            placeholder="ابحث باسم المورد أو رقم الهاتف…"
            className="min-w-[220px] flex-1"
          />
          <StatusTabs
            label="رصيد الموردين"
            value={tab}
            tabs={SUPPLIER_TABS.map((id) => ({ id, label: LABELS[id], count: list.data?.counts[id] }))}
            onChange={(value) => {
              setTab(value);
              resetPage();
            }}
          />
          <FilterPanel
            activeCount={minBalance > 0 ? 1 : 0}
            onApply={() => {
              setMinBalance(Number(minDraft) || 0);
              resetPage();
            }}
            onClear={() => {
              setMinDraft("");
              setMinBalance(0);
              resetPage();
            }}
          >
            <Field label="الحد الأدنى للرصيد (د.ع)" wide>
              <NumberInput value={minDraft} onChange={setMinDraft} placeholder="أي رصيد" />
            </Field>
          </FilterPanel>
        </div>
        <div className="mb-3 flex shrink-0 items-center justify-between gap-3 text-[11px] text-ink-faint">
          <span className="inline-flex items-center gap-1.5">
            <Clock3 size={13} />
            {selection.selected.size > 0
              ? `${formatNumber(selection.selected.size)} مورد محدد`
              : "المبالغ بالدينار العراقي"}
          </span>
          <label className="inline-flex items-center gap-2">
            ترتيب حسب
            <SelectInput
              placeholder="اختر الترتيب"
              value={sort}
              onChange={(v) => {
                setSort((v || "name") as SuppliersQuery["sort"]);
                resetPage();
              }}
              options={[
                { value: "name", label: "الاسم" },
                { value: "balance", label: "الأعلى رصيداً" },
                { value: "recent", label: "آخر تعامل" },
              ]}
            />
          </label>
        </div>
        <DataTable
          label="الموردين"
          columns={columns}
          rows={list.data?.rows}
          loading={loading}
          fetching={list.isFetching}
          error={list.error ? toFinoraError(list.error).message : null}
          onRetry={() => {
            void list.refetch();
          }}
          emptyTitle="لا يوجد موردون"
          emptyHint={
            search || tab !== "all" || minBalance > 0
              ? "جرّب تغيير البحث أو مسح التصفية."
              : "أضف أول مورد لمتابعة مشترياتك وحساباته."
          }
          selection={selection}
          activeId={detailsId}
          onOpen={openDetails}
          rowActions={rowActions}
        />
        <TablePagination
          page={list.data?.page ?? page}
          totalPages={list.data?.total_pages ?? 1}
          total={list.data?.total ?? 0}
          pageSize={pageSize}
          noun="مورد"
          onPage={(v) => {
            setPage(v);
            selection.clear();
          }}
          onPageSize={(v) => {
            setPageSize(v);
            resetPage();
          }}
        />
      </main>
      {active && editor !== null && (
        <SupplierEditor
          key={editor === "create" ? "create" : editor.id}
          supplier={editor === "create" ? undefined : editor}
          draft={editor === "create" ? supplierDraft : null}
          onClose={() => setEditor(null)}
          onSaved={(id) => {
            setEditor(null);
            setDetailsId(id);
          }}
        />
      )}
      {active && paymentOpen && details.data && (
        <SupplierPaymentDialog
          key={details.data.supplier.id}
          details={details.data}
          draft={paymentDraft}
          onClose={() => setPaymentOpen(false)}
        />
      )}
      {active && saleOpen && details.data && (
        <SupplierSaleDialog
          key={details.data.supplier.id}
          supplier={details.data.supplier}
          onClose={() => setSaleOpen(false)}
        />
      )}
      <ConfirmDialog
        open={active && replaceDraft !== null}
        title="بدء فاتورة شراء جديدة"
        message={
          <>
            توجد فاتورة شراء غير محفوظة. بدء فاتورة للمورد <strong>{replaceDraft?.name}</strong> سيستبدل مسودة
            الفاتورة الحالية.
          </>
        }
        confirmLabel="بدء فاتورة جديدة"
        onClose={() => setReplaceDraft(null)}
        onConfirm={() => {
          if (replaceDraft) startPurchase(replaceDraft);
          setReplaceDraft(null);
        }}
      />
    </div>
  );
}
