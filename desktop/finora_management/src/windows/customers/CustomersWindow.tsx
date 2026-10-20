import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, Clock3, FileText, Pencil, Plus, RefreshCw, UsersRound, Wallet } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useWorkspaceHistory, useWorkspaceRequest } from "@/features/workspace/navigation";
import { finora, toFinoraError } from "@/api/finora";
import type { CustomerRow, CustomerTab } from "@/api/finora/customers";
import { DataTable, type Column } from "@/components/DataTable";
import { FeatureHelp } from "@/components/FeatureHelp";
import { SearchBox } from "@/components/SearchBox";
import { SidePanel, DetailRow } from "@/components/SidePanel";
import { StatCard } from "@/components/StatCard";
import { TablePagination } from "@/components/TablePagination";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useWindowManager } from "@/stores/windowManager";
import { useOrderNavigation } from "@/stores/orderNavigation";
import { useFinanceNavigation } from "@/stores/financeNavigation";
import { useCan } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { CustomerEditor } from "./CustomerEditor";
import { CustomerRecovery } from "./CustomerRecovery";
import { CustomerScheduleEditor } from "./CustomerScheduleEditor";
import { CustomerTransactions } from "./CustomerTransactions";
import { CustomerPlanBuilder } from "./CustomerPlanBuilder";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
import { cn } from "@/utils/cn";

const money = (value: number) => `${formatNumber(value)} د.ع`;
const button =
  "rounded-control border border-line bg-white/80 px-4 py-2 text-sm text-ink-soft hover:bg-violet-soft";
const tabs: { id: CustomerTab; name: string }[] = [
  { id: "all", name: "كل العملاء" },
  { id: "debt", name: "عليهم مستحقات" },
  { id: "overdue", name: "أقساط متأخرة" },
  { id: "settled", name: "بدون دين" },
];
const statusNames: Record<string, string> = {
  paid: "مسدد",
  overdue: "متأخر",
  partial: "جزئي",
  pending: "قادم",
};

function CustomerDetails({
  id,
  onClose,
  onEdit,
}: {
  id: number;
  onClose(): void;
  onEdit(row: CustomerRow): void;
}) {
  const canOpenOrders = useCan("can_see_orders");
  const canViewFinance = useCan("finance.view");
  const canCollect = useCan("finance.create");
  const canSchedule = useCan("manage_customers");
  const canRegisterDebt = useCan("finance.settings");
  const online = useConnection((state) => state.status === "online");
  const print = useMutation({
    mutationFn: () => finora.customers.printStatement(id),
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  const [tab, setTab] = useState<"invoices" | "installments" | "receivables">("invoices");
  const [page, setPage] = useState(1);
  const [schedulePlan, setSchedulePlan] = useState<number | null>(null);
  const [createInvoicePlan, setCreateInvoicePlan] = useState<number | null>(null);
  const [createOpeningDebt, setCreateOpeningDebt] = useState(false);
  const [transactions, setTransactions] = useState<"collections" | "history" | null>(null);
  const detail = useQuery({
    queryKey: ["customers", "detail", id],
    queryFn: () => finora.customers.detail(id),
  });
  const invoices = useQuery({
    queryKey: ["customers", "history", id, "invoices", page],
    queryFn: () => finora.customers.invoices(id, page),
    enabled: tab === "invoices",
  });
  const installments = useQuery({
    queryKey: ["customers", "history", id, "installments", page],
    queryFn: () => finora.customers.installments(id, page),
    enabled: tab === "installments",
  });
  const receivables = useQuery({
    queryKey: ["customers", "history", id, "receivables", page],
    queryFn: () => finora.customers.receivables(id, page),
    enabled: tab === "receivables",
  });
  const history = tab === "invoices" ? invoices : tab === "installments" ? installments : receivables;
  const row = detail.data;
  return (
    <>
      <SidePanel
        open
        title={row?.name ?? "ملف العميل"}
        subtitle={row?.phone}
        onClose={onClose}
        actions={
          row && (
            <button className={button} aria-label="تعديل ملف العميل" onClick={() => onEdit(row)}>
              <Pencil size={16} />
            </button>
          )
        }
      >
        {detail.isPending && <p role="status">جارٍ تحميل ملف العميل…</p>}
        {detail.error && (
          <p role="alert" className="text-danger">
            {toFinoraError(detail.error).message}
            <button className={button} onClick={() => void detail.refetch()}>
              إعادة المحاولة
            </button>
          </p>
        )}
        {row && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-panel bg-violet-soft p-4">
                <p className="text-xs text-ink-soft">الدين الحالي</p>
                <strong className="mt-2 block ltr-isolate text-lg">{money(row.debt)}</strong>
              </div>
              <div className="rounded-panel bg-warning-soft p-4">
                <p className="text-xs text-ink-soft">الأقساط المتأخرة</p>
                <strong className="mt-2 block ltr-isolate text-lg">{money(row.overdue)}</strong>
              </div>
            </div>
            <div>
              <button className={button} disabled={!online} onClick={() => setTransactions("collections")}>
                حركات التحصيل والتسويات
              </button>
              {canRegisterDebt && canViewFinance && canSchedule && (
                <button
                  className={`${button} mx-2`}
                  disabled={!online}
                  onClick={() => setCreateOpeningDebt(true)}
                >
                  تسجيل دين افتتاحي
                </button>
              )}
              <DetailRow label="المحافظة">{row.city || "—"}</DetailRow>
              <button
                className={`${button} my-2`}
                disabled={!online}
                onClick={() => setTransactions("history")}
              >
                كشف الحساب التاريخي
              </button>
              <DetailRow label="العنوان">{row.address || "—"}</DetailRow>
              <DetailRow label="هاتف إضافي">{row.phone2 || "—"}</DetailRow>
              <DetailRow label="ملاحظات">{row.notes || "—"}</DetailRow>
            </div>
            <div role="tablist" aria-label="سجل العميل" className="flex gap-2">
              {(["invoices", "installments", "receivables"] as const).map((value) => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={tab === value}
                  className={cn(button, tab === value && "bg-violet-soft text-violet-deep")}
                  onClick={() => {
                    setTab(value);
                    setPage(1);
                  }}
                >
                  {value === "invoices" ? "الفواتير" : value === "installments" ? "الأقساط" : "كشف المستحقات"}
                </button>
              ))}
            </div>
            {history.isPending && <p role="status">جارٍ تحميل السجل…</p>}
            {history.error && (
              <p role="alert" className="text-danger">
                {toFinoraError(history.error).message}
                <button className={button} onClick={() => void history.refetch()}>
                  إعادة المحاولة
                </button>
              </p>
            )}
            {history.data?.total === 0 && (
              <p className="rounded-panel bg-white p-5 text-center text-ink-faint">
                {tab === "invoices"
                  ? "لا توجد فواتير"
                  : tab === "installments"
                    ? "لا توجد أقساط"
                    : "لا توجد مستندات مستحقة"}
              </p>
            )}
            {tab === "receivables" && receivables.data && (
              <div className="space-y-3">
                <div className="rounded-panel bg-violet-soft p-4 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <strong>المستحقات الحالية</strong>
                    <FeatureHelp text="يعرض المستندات التي عليها مبلغ متبقٍ الآن، وليس رصيداً تاريخياً. خطة أقساط الفاتورة لا تضيف ديناً ثانياً. التسديد المحتسب يشمل التسويات المسجلة على المستند." />
                  </div>
                  <button
                    className={cn(button, "mt-3 disabled:opacity-50")}
                    disabled={!online || print.isPending}
                    onClick={() => print.mutate()}
                  >
                    {print.isPending ? "جارٍ فتح الطباعة…" : "طباعة الكشف / PDF"}
                  </button>
                  <p className="mt-1 text-xs text-ink-soft">كما في {receivables.data.as_of}</p>
                  <DetailRow label="أصل المستندات">{money(receivables.data.summary.total)}</DetailRow>
                  <DetailRow label="التسديد المحتسب">{money(receivables.data.summary.paid)}</DetailRow>
                  <DetailRow label="المتبقي الحالي">{money(receivables.data.summary.remaining)}</DetailRow>
                </div>
                {receivables.data.items.map((item) => (
                  <article
                    key={`${item.kind}:${item.id}`}
                    className="rounded-panel border border-line bg-white p-4"
                  >
                    <strong>
                      {item.kind === "invoice" ? `فاتورة #${item.id}` : item.description || "دين مستقل"}
                    </strong>
                    <p className="my-2 text-xs text-ink-faint">{item.date?.slice(0, 10) ?? "—"}</p>
                    <DetailRow label="الأصل">{money(item.total)}</DetailRow>
                    <DetailRow label="التسديد المحتسب">{money(item.paid)}</DetailRow>
                    <DetailRow label="المتبقي">{money(item.remaining)}</DetailRow>
                    {canViewFinance && canCollect && item.remaining > 0 && (
                      <div className="my-3 flex items-center gap-2">
                        <button
                          className={button}
                          disabled={!online}
                          onClick={() => {
                            useFinanceNavigation.getState().collect({
                              customerId: row.id,
                              customerName: row.name,
                              branchId: item.branch_id ?? row.branch_id,
                              invoiceId: item.id,
                              documentKind: item.kind,
                              remaining: item.remaining,
                            });
                            useWindowManager.getState().open("finance");
                          }}
                        >
                          {item.kind === "invoice" ? "تحصيل الفاتورة" : "تحصيل الدين"}
                        </button>
                        <FeatureHelp text="يفتح سنداً لهذا المستند فقط. راجع المبلغ والحساب؛ المسودة لا تغير الأرصدة، والاعتماد يخفض الدين ويحدث الأقساط مرة واحدة. الديون المستقلة السابقة تحتاج اعتماداً من مراجعة الأرصدة الافتتاحية بإعدادات الحسابات، ولا تُحسب إيراداً جديداً." />
                      </div>
                    )}
                    {canOpenOrders && item.invoice_id !== null && (
                      <button
                        className={button}
                        onClick={() => {
                          if (item.invoice_id !== null) {
                            useOrderNavigation.getState().open(item.invoice_id);
                            useWindowManager.getState().open("orders");
                          }
                        }}
                      >
                        فتح الفاتورة الأصلية
                      </button>
                    )}
                  </article>
                ))}
              </div>
            )}
            {tab === "invoices" &&
              invoices.data?.items.map((invoice) => (
                <article key={invoice.id} className="space-y-2 rounded-panel border border-line bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <strong>فاتورة #{invoice.number}</strong>
                    <span className="text-xs text-ink-soft">{invoice.status}</span>
                  </div>
                  <p className="text-xs text-ink-faint">{invoice.date?.slice(0, 10) ?? "—"}</p>
                  <DetailRow label="الإجمالي">{money(invoice.total)}</DetailRow>
                  <DetailRow label="المدفوع المسجل">{money(invoice.paid)}</DetailRow>
                  <DetailRow label="حالة الدفع">{invoice.payment_status || "—"}</DetailRow>
                  {canSchedule && (
                    <button
                      className={button}
                      disabled={!online}
                      onClick={() => setCreateInvoicePlan(invoice.id)}
                    >
                      إنشاء جدول أقساط
                    </button>
                  )}
                  {canOpenOrders && (
                    <button
                      className={button}
                      onClick={() => {
                        useOrderNavigation.getState().open(invoice.id);
                        useWindowManager.getState().open("orders");
                      }}
                    >
                      فتح الفاتورة الأصلية
                    </button>
                  )}
                </article>
              ))}
            {tab === "installments" &&
              installments.data?.items.map((item) => (
                <article key={item.id} className="space-y-2 rounded-panel border border-line bg-white p-4">
                  <div className="flex items-center justify-between">
                    <strong>قسط {item.number}</strong>
                    <span
                      className={cn(
                        "rounded-full px-3 py-1 text-xs",
                        item.status === "overdue"
                          ? "bg-warning-soft text-warning"
                          : "bg-violet-soft text-violet-deep",
                      )}
                    >
                      {statusNames[item.status] ?? item.status}
                    </span>
                  </div>
                  <p className="text-xs text-ink-soft">
                    الاستحقاق: {item.date}
                    {item.invoice_id ? ` · فاتورة #${item.invoice_id}` : " · دين مستقل"}
                  </p>
                  <DetailRow label="قيمة القسط">{money(item.total)}</DetailRow>
                  <DetailRow label="المدفوع">{money(item.paid)}</DetailRow>
                  <DetailRow label="المتبقي">{money(item.remaining)}</DetailRow>
                  {canSchedule &&
                    installments.data?.items.find((row) => row.plan_id === item.plan_id)?.id === item.id && (
                      <button
                        type="button"
                        disabled={!online}
                        className={button}
                        aria-label={`جدولة الخطة ${item.plan_id}`}
                        onClick={() => setSchedulePlan(item.plan_id)}
                      >
                        جدولة الأقساط وتاريخ التعديل
                      </button>
                    )}
                </article>
              ))}
            {history.data && history.data.total > 25 && (
              <div className="flex items-center justify-between">
                <button className={button} disabled={page === 1} onClick={() => setPage(page - 1)}>
                  السابق
                </button>
                <span>
                  {page} / {Math.ceil(history.data.total / 25)}
                </span>
                <button
                  className={button}
                  disabled={page * 25 >= history.data.total}
                  onClick={() => setPage(page + 1)}
                >
                  التالي
                </button>
              </div>
            )}
          </div>
        )}
      </SidePanel>
      {schedulePlan !== null && (
        <CustomerScheduleEditor customerId={id} planId={schedulePlan} onClose={() => setSchedulePlan(null)} />
      )}
      {createOpeningDebt && (
        <CustomerPlanBuilder
          customerId={id}
          openingDebt
          onClose={() => setCreateOpeningDebt(false)}
          onSaved={(data) => {
            setCreateOpeningDebt(false);
            setSchedulePlan(data.id);
          }}
        />
      )}
      {createInvoicePlan !== null && (
        <CustomerPlanBuilder
          customerId={id}
          invoiceId={createInvoicePlan}
          onClose={() => setCreateInvoicePlan(null)}
          onSaved={(data) => {
            setCreateInvoicePlan(null);
            setSchedulePlan(data.id);
          }}
        />
      )}
      {transactions && row && (
        <CustomerTransactions
          historical={transactions === "history"}
          customerId={id}
          customerName={row.name}
          onClose={() => setTransactions(null)}
          onSchedule={(planId) => {
            setTransactions(null);
            setSchedulePlan(planId);
          }}
        />
      )}
    </>
  );
}

export function CustomersWindow() {
  const active = useWindowManager((s) => s.active === "customers");
  const [searchText, setSearchText] = useState("");
  const q = useDebouncedValue(searchText, 250);
  const [tab, setTab] = useState<CustomerTab>("all");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(25);
  const [selected, setSelected] = useState<number | null>(null);
  const [editor, setEditor] = useState<"create" | CustomerRow | null>(null);
  useWorkspaceRequest("customers", (target, action) => {
    if (action === "customer") setEditor((current) => current ?? "create");
    if (target.tab && ["all", "debt", "overdue", "settled"].includes(target.tab)) {
      setTab(target.tab as CustomerTab);
      setPage(1);
    }
    if (target.entityId) setSelected(target.entityId);
    if (target.page) setPage(target.page);
  });
  useWorkspaceHistory({ window: "customers", tab, page, ...(selected ? { entityId: selected } : {}) });
  const online = useConnection((state) => state.status === "online");
  const [compactHeight, setCompactHeight] = useState(() => window.innerHeight <= 800);
  const [summaryOverride, setSummaryOverride] = useState<boolean | null>(null);
  const showSummary = summaryOverride ?? !compactHeight;
  useEffect(() => {
    const resize = () => setCompactHeight(window.innerHeight <= 800);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const query = useMemo(() => ({ q, tab, page, page_size: size }), [q, tab, page, size]);
  const list = useQuery({
    queryKey: ["customers", "list", query],
    queryFn: () => finora.customers.list(query),
    enabled: active,
  });
  const stats = list.data?.stats;
  const columns: Column<CustomerRow>[] = [
    {
      id: "name",
      header: "العميل",
      cell: (row) => (
        <div>
          <strong>{row.name}</strong>
          <span className="mt-1 block text-xs text-ink-faint">{row.city || "—"}</span>
        </div>
      ),
    },
    { id: "phone", header: "الهاتف", cell: (row) => <span className="ltr-isolate">{row.phone}</span> },
    {
      id: "debt",
      header: "الدين الحالي",
      cell: (row) => <strong className="ltr-isolate">{money(row.debt)}</strong>,
    },
    {
      id: "overdue",
      header: "الأقساط المتأخرة",
      cell: (row) => (
        <span className={cn("ltr-isolate", row.overdue > 0 && "font-semibold text-warning")}>
          {money(row.overdue)}
        </span>
      ),
    },
    {
      id: "address",
      header: "العنوان",
      minTableWidth: 1050,
      cell: (row) => <span className="block max-w-[240px] truncate">{row.address || "—"}</span>,
    },
  ];
  return (
    <div className="relative flex h-full min-h-0 flex-col gap-3">
      <div className="flex shrink-0 items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            className="flex h-10 items-center gap-2 rounded-control bg-gradient-to-l from-violet to-violet-deep px-4 text-sm font-semibold text-white disabled:opacity-50"
            disabled={!online}
            onClick={() => {
              setSelected(null);
              setEditor("create");
            }}
          >
            <Plus size={17} />
            إضافة عميل
          </button>
          <span className="text-sm text-ink-soft">متابعة العملاء والمستحقات</span>
          <FeatureHelp text="الدين الحالي يجمع الفواتير المستحقة والديون المستقلة. أقساط الفاتورة جزء من دينها ولا تُضاف إليه مرة ثانية. الأرقام تعرض الرصيد الحالي." />
        </div>
        <div className="flex items-center gap-2">
          <button
            className={cn(button, "flex items-center gap-2")}
            aria-expanded={showSummary}
            aria-controls="customer-summary"
            onClick={() => setSummaryOverride(!showSummary)}
          >
            ملخص العملاء
            <ChevronDown
              size={16}
              className={cn(
                "transition-transform motion-reduce:transition-none",
                showSummary && "rotate-180",
              )}
            />
          </button>
          <button className={button} aria-label="تحديث العملاء" onClick={() => void list.refetch()}>
            <RefreshCw size={17} />
          </button>
        </div>
      </div>
      <CustomerRecovery active={active} editing={editor !== null} onRecovered={setSelected} />
      {showSummary && (
        <div id="customer-summary" className="grid shrink-0 grid-cols-4 gap-3">
          <StatCard
            label="العملاء"
            value={formatNumber(stats?.customers ?? 0)}
            icon={UsersRound}
            tone="azure"
            loading={list.isPending}
          />
          <StatCard
            label="المستحقات الحالية"
            value={formatNumber(stats?.debt ?? 0)}
            unit="د.ع"
            icon={Wallet}
            tone="violet"
            loading={list.isPending}
          />
          <StatCard
            label="أقساط متأخرة"
            value={formatNumber(stats?.overdue ?? 0)}
            unit="د.ع"
            icon={Clock3}
            tone="warning"
            loading={list.isPending}
          />
          <StatCard
            label="عملاء عليهم دين"
            value={formatNumber(stats?.debtors ?? 0)}
            icon={FileText}
            tone="danger"
            loading={list.isPending}
          />
        </div>
      )}
      <div className="flex shrink-0 items-center gap-3">
        <SearchBox
          className="min-w-0 flex-1"
          value={searchText}
          onChange={(value) => {
            setSearchText(value);
            setPage(1);
          }}
          placeholder="ابحث باسم العميل أو رقم الهاتف…"
        />
        <div role="tablist" aria-label="تصفية العملاء" className="flex shrink-0 gap-2">
          {tabs.map((item) => (
            <button
              role="tab"
              key={item.id}
              aria-selected={item.id === tab}
              className={cn(button, item.id === tab && "border-violet/40 bg-violet-soft text-violet-deep")}
              onClick={() => {
                setTab(item.id);
                setPage(1);
              }}
            >
              {item.name}
            </button>
          ))}
        </div>
      </div>
      <DataTable
        label="جدول العملاء"
        rows={list.data?.items}
        columns={columns}
        loading={list.isPending}
        fetching={list.isFetching}
        error={list.error ? toFinoraError(list.error).message : null}
        onRetry={() => void list.refetch()}
        emptyTitle="لا يوجد عملاء مطابقون"
        activeId={selected}
        onOpen={(row) => setSelected(row.id)}
      />
      <div className="shrink-0">
        <TablePagination
          page={page}
          totalPages={Math.max(1, Math.ceil((list.data?.total ?? 0) / size))}
          total={list.data?.total ?? 0}
          pageSize={size}
          noun="عميل"
          onPage={setPage}
          onPageSize={(value) => {
            setSize(value);
            setPage(1);
          }}
        />
      </div>
      {active && selected !== null && (
        <CustomerDetails
          key={selected}
          id={selected}
          onClose={() => setSelected(null)}
          onEdit={(row) => {
            setSelected(null);
            setEditor(row);
          }}
        />
      )}
      {active && editor !== null && (
        <CustomerEditor
          row={editor === "create" ? undefined : editor}
          onClose={() => setEditor(null)}
          onSaved={(row) => {
            setEditor(null);
            setSelected(row.id);
          }}
        />
      )}
    </div>
  );
}
