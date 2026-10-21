import { useTimeFormat } from "@/stores/displayTime";
import { useAssistantDraftFields } from "@/features/assistant/draftQueue";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useWorkspaceHistory, useWorkspaceRequest } from "@/features/workspace/navigation";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Clock3,
  FileText,
  Plus,
  Printer,
  RefreshCw,
  Wallet,
  Settings2,
  Download,
} from "lucide-react";
import { useEffect, useMemo, useState, useId, cloneElement, isValidElement, type ReactNode } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { FinanceAccount, FinanceLoan, FinanceMeta, FinanceVoucher } from "@/api/finora/finance";
import { DataTable, type Column } from "@/components/DataTable";
import { FeatureHelp } from "@/components/FeatureHelp";
import { SidePanel, DetailRow } from "@/components/SidePanel";
import { StatCard } from "@/components/StatCard";
import { SearchBox } from "@/components/SearchBox";
import { TablePagination } from "@/components/TablePagination";
import { useWindowManager } from "@/stores/windowManager";
import { useFinanceNavigation, type CustomerCollection } from "@/stores/financeNavigation";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { formatNumber, formatDateTime } from "@/utils/format";
import { cn } from "@/utils/cn";
import { CashShifts } from "./CashShifts";
import { FinancialControl } from "./FinancialControl";

const primary =
  "h-10 rounded-control bg-gradient-to-l from-violet to-violet-deep px-4 text-sm font-semibold text-white shadow-control disabled:opacity-50";
const secondary =
  "h-10 rounded-control border border-line bg-white/70 px-3 text-sm text-ink-soft hover:bg-violet-soft disabled:opacity-50";
const input =
  "h-11 min-w-0 rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:ring-2 focus:ring-violet/30";
const money = (n: number) => `${formatNumber(n)} د.ع`;
const statuses: Record<string, string> = {
  draft: "مسودة",
  pending: "بانتظار الاعتماد",
  posted: "مرحّل",
  reversed: "معكوس",
  rejected: "مرفوض",
  cancelled: "ملغى",
  active: "فعال",
  closed: "مسدد",
  paid: "مسدد",
  partial: "جزئي",
  overdue: "متأخر",
  matched: "مطابق",
};
const isoToday = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Baghdad",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
type Tab = "vouchers" | "loans" | "accounts" | "journal" | "shifts" | "control";
type Selected = { type: "voucher" | "loan" | "account"; id: number };
const documentLabels: Record<string, string> = {
  credit_plan_payment: "دفعة قسط",
  credit_plan_reversal: "عكس دفعة قسط",
  customer_debt: "دين مستقل",
  invoice: "فاتورة بيع",
  purchase: "فاتورة مشتريات",
  expense: "مصروف",
  supplier_payment: "دفعة مورد",
  receipt: "سند قبض",
  credit: "رصيد مقدم",
  loan: "عقد قرض",
  hr_advance: "سلفة موظف",
};
const auditLabels: Record<string, string> = {
  create: "إنشاء مسودة",
  edit: "تعديل مسودة",
  post: "اعتماد وترحيل",
  submit: "طلب اعتماد",
  reverse: "عكس العملية",
  reject: "رفض الطلب",
  cancel: "إلغاء المسودة",
  apply_credit: "تطبيق رصيد مقدم",
  "source.post": "ترحيل المستند الأصلي",
  "attachment.add": "إضافة إثبات",
  "contract.create": "إنشاء عقد",
  fund: "تمويل العقد",
  payment: "تسجيل قسط",
  reschedule: "إعادة الجدولة",
  close: "إغلاق العقد",
};
function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  useTimeFormat();
  const id = useId();
  return (
    <div className="grid min-w-0 gap-2 text-sm text-ink-soft [&>input]:w-full [&>select]:w-full [&>textarea]:w-full">
      <span className="flex items-center gap-2">
        <label htmlFor={id}>{label}</label>
        {help && <FeatureHelp text={help} />}
      </span>
      {isValidElement<{ id?: string }>(children) ? cloneElement(children, { id }) : children}
    </div>
  );
}
function Badge({ status }: { status: string }) {
  useTimeFormat();
  return (
    <span
      className={cn(
        "rounded-full px-3 py-1 text-xs",
        status === "posted" || status === "paid" || status === "matched"
          ? "bg-success-soft text-success"
          : status === "pending" || status === "overdue"
            ? "bg-warning-soft text-warning"
            : "bg-violet-soft text-violet-deep",
      )}
    >
      {statuses[status] || status}
    </span>
  );
}

export function FinanceWindow() {
  useTimeFormat();
  const active = useWindowManager((s) => s.active === "finance");
  const online = useConnection((s) => s.status === "online");
  const cache = useQueryClient();
  const [editing, setEditing] = useState<FinanceVoucher | null>(null);
  const [exporting, setExporting] = useState(false);
  const [tab, setTab] = useState<Tab>("vouchers");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [statement, setStatement] = useState<{ type: "customer" | "supplier"; id: number } | null>(null);
  const [editor, setEditor] = useState<"voucher" | "loan" | "settings" | "reconciliation" | null>(null);
  const [initialCategory, setInitialCategory] = useState<string | undefined>();
  useWorkspaceHistory({
    window: "finance",
    tab,
    ...(selected?.type === "voucher" ? { entityId: selected.id } : {}),
  });
  const requestedCollection = useFinanceNavigation((state) => state.collection);
  const requestedVoucher = useFinanceNavigation((state) => state.voucherId);
  const [collection, setCollection] = useState<CustomerCollection | null>(null);
  const [operation, setOperation] = useState<{ name: string; row: FinanceVoucher | FinanceLoan } | null>(
    null,
  );
  const meta = useQuery({
    queryKey: ["finance", "meta"],
    queryFn: () => finora.finance.meta(),
    enabled: active,
  });
  const caps = meta.data?.capabilities || {};
  useWorkspaceRequest(
    "finance",
    (target, action) => {
      if (action === "receipt") {
        if (!caps["finance.create"]) {
          toast.error("تحتاج صلاحية إنشاء سند مالي");
          return;
        }
        if (editor) {
          toast.info("أكمل النموذج المالي المفتوح أو أغلقه أولاً");
          return;
        }
        setEditing(null);
        setInitialCategory("customer_payment");
        setEditor("voucher");
        setTab("vouchers");
      }
      const permissions: Record<string, string> = {
        vouchers: "finance.view",
        loans: "finance.loans",
        journal: "finance.ledger",
        accounts: "finance.view",
        control: "finance.reconcile",
        shifts: "finance.view",
      };
      if (target.tab && permissions[target.tab] && caps[permissions[target.tab] ?? ""])
        setTab(target.tab as Tab);
      if (target.dateFrom) setFrom(target.dateFrom);
      if (target.dateTo) setTo(target.dateTo);
      if (target.entityId && caps["finance.view"]) {
        setTab("vouchers");
        setSelected({ type: "voucher", id: target.entityId });
      }
    },
    !!meta.data,
  );

  useEffect(() => {
    if (!active || !requestedVoucher || !meta.data || editor) return;
    if (meta.data.capabilities["finance.view"]) {
      setTab("vouchers");
      setSelected({ type: "voucher", id: requestedVoucher });
    } else toast.error("تحتاج صلاحية عرض الحسابات لفتح السند");
    useFinanceNavigation.getState().clear();
  }, [active, requestedVoucher, meta.data, editor]);
  useEffect(() => {
    if (!active || !requestedCollection || !meta.data || editor) return;
    if (!meta.data.capabilities["finance.create"]) {
      useFinanceNavigation.getState().clear();
      toast.error("تحتاج صلاحية إنشاء سند مالي للتحصيل");
      return;
    }
    setEditing(null);
    setTab("vouchers");
    setSelected(null);
    setCollection(requestedCollection);
    setEditor("voucher");
    useFinanceNavigation.getState().clear();
  }, [active, requestedCollection, meta.data, editor]);
  const exportVouchers = async () => {
    setExporting(true);
    try {
      const data = await finora.finance.exportVouchers(query);
      if (!data) throw Error("تعذر تصدير السندات");
      const url = URL.createObjectURL(new Blob([data.content], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast.error(toFinoraError(e).message);
    } finally {
      setExporting(false);
    }
  };
  const query = useMemo(
    () => ({
      q: search,
      status,
      date_from: from,
      date_to: to,
      treasury_account_id: accountFilter,
      kind,
      page,
      page_size: pageSize,
    }),
    [search, status, from, to, accountFilter, kind, page, pageSize],
  );
  const vouchers = useQuery({
    queryKey: ["finance", "vouchers", query],
    queryFn: () => finora.finance.vouchers(query),
    enabled: active && tab === "vouchers",
  });
  const loans = useQuery({
    queryKey: ["finance", "loans", query],
    queryFn: () => finora.finance.loans(query),
    enabled: active && tab === "loans",
  });
  const journal = useQuery({
    queryKey: ["finance", "journal", query],
    queryFn: () => finora.finance.journal(query),
    enabled: active && tab === "journal" && caps["finance.ledger"],
  });
  const trial = useQuery({
    queryKey: ["finance", "trial", from, to],
    queryFn: () => finora.finance.trial({ date_from: from, date_to: to }),
    enabled: active && tab === "journal" && caps["finance.ledger"],
  });
  const detail = useQuery({
    queryKey: ["finance", "detail", selected],
    queryFn: async () => {
      if (!selected) throw Error("اختر سجلاً");
      return selected.type === "voucher"
        ? finora.finance.voucher(selected.id)
        : selected.type === "loan"
          ? finora.finance.loan(selected.id)
          : finora.finance.ledger(selected.id);
    },
    enabled: active && selected !== null,
  });
  const notices = useQuery({
    queryKey: ["finance", "notices"],
    queryFn: () => finora.finance.notices(),
    enabled: active,
  });
  const refresh = () =>
    Promise.all([
      cache.invalidateQueries({ queryKey: ["finance"] }),
      cache.invalidateQueries({ queryKey: ["customers"] }),
    ]);
  useEffect(() => {
    setPage(1);
  }, [search, status, from, to, accountFilter, kind, tab]);
  const changeTab = (value: Tab) => {
    setTab(value);
    setSelected(null);
    setStatus("");
  };
  const row = detail.data;
  const v = selected?.type === "voucher" ? (row as FinanceVoucher | undefined) : undefined;
  const l = selected?.type === "loan" ? (row as FinanceLoan | undefined) : undefined;
  const a =
    selected?.type === "account"
      ? (row as Awaited<ReturnType<typeof finora.finance.ledger>> | undefined)
      : undefined;
  const stats = tab === "loans" ? loans.data?.stats : vouchers.data?.stats;
  const err = (e: unknown) => (e ? toFinoraError(e).message : null);
  const voucherColumns: Column<FinanceVoucher>[] = [
    {
      id: "number",
      header: "السند / التاريخ",
      cell: (r) => (
        <div>
          <b>{r.number}</b>
          <div className="mt-1 text-xs text-ink-faint">{r.transaction_date}</div>
        </div>
      ),
    },
    {
      id: "party",
      header: "الجهة / السبب",
      cell: (r) => (
        <div>
          {r.party_name}
          <div className="mt-1 text-xs text-ink-faint">{r.category_label}</div>
        </div>
      ),
    },
    {
      id: "kind",
      header: "نوع العملية",
      cell: (r) =>
        ({ receipt: "قبض", payment: "صرف", transfer: "تحويل", settlement: "تسوية" })[r.kind] || r.kind,
      minTableWidth: 700,
    },
    { id: "amount", header: "المبلغ", cell: (r) => <b>{money(r.amount)}</b> },
    { id: "account", header: "الحساب", cell: (r) => r.account_name, minTableWidth: 850 },
    { id: "status", header: "الحالة", cell: (r) => <Badge status={r.status} /> },
  ];
  const loanColumns: Column<FinanceLoan>[] = [
    {
      id: "number",
      header: "العقد / الجهة",
      cell: (r) => (
        <div>
          <b>{r.number}</b>
          <div className="mt-1 text-xs text-ink-soft">{r.party_name}</div>
        </div>
      ),
    },
    { id: "principal", header: "أصل القرض", cell: (r) => money(r.principal) },
    {
      id: "remaining",
      header: "المتبقي",
      cell: (r) => (
        <div>
          <b>{money(r.remaining_total)}</b>
          <div className="mt-2 h-1.5 rounded-full bg-line">
            <div style={{ width: `${r.progress}%` }} className="h-full rounded-full bg-violet" />
          </div>
        </div>
      ),
    },
    {
      id: "next",
      header: "القسط القادم",
      cell: (r) => (
        <div>
          {r.next_due || "—"}
          <div className="text-xs text-ink-soft">{money(r.next_amount)}</div>
        </div>
      ),
      minTableWidth: 700,
    },
    { id: "status", header: "الحالة", cell: (r) => <Badge status={r.overdue ? "overdue" : r.status} /> },
  ];
  return (
    <div
      className="relative flex h-full min-h-0 flex-col gap-4 [@media(max-height:700px)]:overflow-y-auto"
      dir="rtl"
      data-testid="finance-window"
    >
      <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="أقسام الحسابات">
        {(
          [
            ["vouchers", "القبض والصرف"],
            ["loans", "السلف والقروض"],
            ["accounts", "الصناديق والحسابات"],
            ["shifts", "ورديات الصندوق"],
            ["control", "الرقابة المالية"],
            ["journal", "القيود والتقارير"],
          ] as const
        )
          .filter(
            ([id]) =>
              (id !== "journal" || caps["finance.ledger"]) &&
              (id !== "shifts" || meta.data?.cash_shifts_available) &&
              (id !== "control" || (meta.data?.financial_control_available && caps["finance.ledger"])),
          )
          .map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              disabled={
                (id === "shifts" || id === "control") && !!(editor || operation || selected || statement)
              }
              className={tab === id ? primary : secondary}
              onClick={() => changeTab(id)}
            >
              {label}
            </button>
          ))}
        <FeatureHelp text="السند المسودة لا يؤثر على الأرصدة. الاعتماد يرحّل العملية، وتصحيح السند المرحّل يكون بعكسه مع الاحتفاظ بالتاريخ." />
        <div className="flex-1" />
        {caps["finance.settings"] && tab !== "shifts" && tab !== "control" && (
          <button className={secondary} aria-label="إعدادات الحسابات" onClick={() => setEditor("settings")}>
            <Settings2 size={18} />
          </button>
        )}
        <button className={secondary} aria-label="تحديث" onClick={() => void refresh()}>
          <RefreshCw size={18} />
        </button>
      </div>
      {!online && (
        <p role="status" className="rounded-control bg-warning-soft p-3 text-sm text-warning">
          الاتصال غير متاح. الاعتماد وتحريك الأرصدة يحتاجان اتصالاً بالخادم.
        </p>
      )}
      {meta.error && (
        <p role="alert" className="text-danger">
          {err(meta.error)} <button onClick={() => void meta.refetch()}>إعادة المحاولة</button>
        </p>
      )}
      {requestedCollection && editor && (
        <p role="status" className="rounded-control bg-violet-soft p-3 text-sm text-violet-deep">
          تحصيل {requestedCollection.documentKind === "credit_plan" ? "الدين" : "الفاتورة"} #
          {requestedCollection.invoiceId} بانتظارك. احفظ النموذج الحالي أو أغلقه قبل فتح التحصيل.
          <button className={secondary} onClick={() => useFinanceNavigation.getState().clear()}>
            إلغاء الانتقال
          </button>
        </p>
      )}
      {tab === "control" ? (
        <FinancialControl
          online={online}
          canMeasure={!!caps["finance.reconcile"]}
          canPrint={!!caps["finance.print"]}
          onAccount={(id) => {
            setTab("accounts");
            setSelected({ type: "account", id });
          }}
          onLoans={() => setTab("loans")}
        />
      ) : tab === "shifts" ? (
        <CashShifts meta={meta.data} online={online} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {tab === "journal" ? (
              <>
                <StatCard
                  label="الإيرادات"
                  value={formatNumber(trial.data?.revenue || 0)}
                  unit="د.ع"
                  icon={ArrowDownLeft}
                  tone="success"
                />
                <StatCard
                  label="المصاريف"
                  value={formatNumber(trial.data?.expenses || 0)}
                  unit="د.ع"
                  icon={ArrowUpRight}
                  tone="danger"
                />
                <StatCard
                  label="صافي الربح"
                  value={formatNumber(trial.data?.profit || 0)}
                  unit="د.ع"
                  icon={FileText}
                  tone="violet"
                />
                <StatCard
                  label="توازن القيود"
                  value={trial.data?.balanced ? "متوازن" : "—"}
                  icon={Wallet}
                  tone="azure"
                />
              </>
            ) : tab === "accounts" ? (
              <>
                <StatCard
                  label="مجموع النقد"
                  value={formatNumber(meta.data?.accounts.reduce((n, a) => n + a.balance, 0) || 0)}
                  unit="د.ع"
                  icon={Wallet}
                  tone="violet"
                />
                {[
                  { type: "cash", name: "الصناديق" },
                  { type: "bank", name: "المصارف" },
                  { type: "wallet", name: "المحافظ" },
                ].map((a) => (
                  <StatCard
                    key={a.type}
                    label={a.name}
                    value={formatNumber(meta.data?.accounts.filter((r) => r.type === a.type).length || 0)}
                    icon={Wallet}
                    tone="azure"
                  />
                ))}
              </>
            ) : (
              <>
                <StatCard
                  label={tab === "loans" ? "أصل القروض الفعالة" : "المقبوضات"}
                  value={formatNumber(stats?.[tab === "loans" ? "principal" : "received"] || 0)}
                  unit="د.ع"
                  icon={ArrowDownLeft}
                  tone="success"
                />
                <StatCard
                  label={tab === "loans" ? "أصل القروض المتبقي" : "المدفوعات"}
                  value={formatNumber(stats?.[tab === "loans" ? "remaining" : "paid"] || 0)}
                  unit="د.ع"
                  icon={ArrowUpRight}
                  tone="danger"
                />
                <StatCard
                  label={tab === "loans" ? "أقساط هذا الشهر" : "صافي الحركة النقدية"}
                  value={formatNumber(stats?.[tab === "loans" ? "monthly_due" : "cash_flow"] || 0)}
                  unit="د.ع"
                  icon={Wallet}
                  tone="violet"
                />
                <StatCard
                  label={tab === "loans" ? "أقساط متأخرة" : "بانتظار الاعتماد"}
                  value={formatNumber(stats?.[tab === "loans" ? "overdue" : "pending"] || 0)}
                  unit={tab === "loans" ? "د.ع" : "سند"}
                  icon={Clock3}
                  tone="warning"
                />
              </>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-[160px] flex-1">
              <SearchBox value={search} onChange={setSearch} placeholder="ابحث بالسند أو الجهة…" />
            </div>
            <input
              aria-label="من تاريخ"
              type="date"
              className={cn(input, "w-36")}
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
            <input
              aria-label="إلى تاريخ"
              type="date"
              className={cn(input, "w-36")}
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
            {tab === "vouchers" && (
              <>
                <select
                  aria-label="نوع السند"
                  className={cn(input, "w-28")}
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="">كل الأنواع</option>
                  <option value="receipt">قبض</option>
                  <option value="payment">صرف</option>
                  <option value="transfer">تحويل</option>
                  <option value="settlement">تسوية</option>
                </select>
                <select
                  aria-label="الحالة"
                  className={cn(input, "w-36")}
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="">كل الحالات</option>
                  {Object.entries(statuses)
                    .filter(([k]) =>
                      ["draft", "pending", "posted", "reversed", "cancelled", "rejected"].includes(k),
                    )
                    .map(([k, t]) => (
                      <option value={k} key={k}>
                        {t}
                      </option>
                    ))}
                </select>
                <select
                  aria-label="الحساب"
                  className={cn(input, "w-36")}
                  value={accountFilter}
                  onChange={(e) => setAccountFilter(e.target.value)}
                >
                  <option value="">كل الحسابات</option>
                  {meta.data?.accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                {caps["finance.print"] && (
                  <button
                    className={secondary}
                    disabled={!online || exporting}
                    onClick={() => void exportVouchers()}
                  >
                    <Download size={16} />
                    <span className="sr-only">تصدير السندات المطابقة للفلاتر</span>
                  </button>
                )}
              </>
            )}
            {caps["finance.create"] && (tab === "vouchers" || (tab === "loans" && caps["finance.loans"])) && (
              <button className={primary} onClick={() => setEditor(tab === "loans" ? "loan" : "voucher")}>
                <span className="flex items-center gap-2">
                  <Plus size={18} />
                  {tab === "loans" ? "عقد جديد" : "سند جديد"}
                </span>
              </button>
            )}
            {tab === "accounts" && caps["finance.reconcile"] && (
              <button className={primary} onClick={() => setEditor("reconciliation")}>
                مطابقة كشف مصرفي
              </button>
            )}
          </div>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden [@media(max-height:700px)]:h-80 [@media(max-height:700px)]:flex-none">
            {tab === "vouchers" ? (
              <DataTable
                label="السندات المالية"
                rows={vouchers.data?.items}
                columns={voucherColumns}
                loading={vouchers.isLoading}
                fetching={vouchers.isFetching}
                error={err(vouchers.error)}
                onRetry={() => void vouchers.refetch()}
                emptyTitle="لا توجد سندات"
                emptyHint="أنشئ مسودة قبض أو صرف للبدء."
                onOpen={(r) => setSelected({ type: "voucher", id: r.id })}
              />
            ) : tab === "loans" ? (
              <DataTable
                label="القروض والسلف"
                rows={loans.data?.items}
                columns={loanColumns}
                loading={loans.isLoading}
                fetching={loans.isFetching}
                error={err(loans.error)}
                onRetry={() => void loans.refetch()}
                emptyTitle="لا توجد عقود"
                emptyHint="العقد يسجل الاتفاق؛ النقد يتحرك عند التمويل فقط."
                onOpen={(r) => setSelected({ type: "loan", id: r.id })}
              />
            ) : tab === "accounts" ? (
              <DataTable<FinanceAccount>
                label="الحسابات النقدية"
                rows={meta.data?.accounts}
                columns={[
                  { id: "name", header: "الحساب", cell: (r) => r.name },
                  {
                    id: "type",
                    header: "النوع",
                    cell: (r) => ({ cash: "صندوق", bank: "مصرف", wallet: "محفظة" })[r.type] || r.type,
                  },
                  { id: "balance", header: "الرصيد الحالي", cell: (r) => <b>{money(r.balance)}</b> },
                ]}
                loading={meta.isLoading}
                fetching={meta.isFetching}
                error={err(meta.error)}
                onRetry={() => void meta.refetch()}
                emptyTitle="لا توجد حسابات"
                onOpen={(r) => setSelected({ type: "account", id: r.id })}
              />
            ) : (
              <LedgerReview
                from={from}
                to={to}
                canPrint={!!caps["finance.print"] && online}
                journal={
                  <DataTable
                    label="القيود المحاسبية"
                    rows={journal.data?.rows}
                    columns={[
                      {
                        id: "number",
                        header: "القيد",
                        cell: (r) => (
                          <div>
                            {r.number}
                            <small className="block text-ink-faint">{r.date}</small>
                          </div>
                        ),
                      },
                      { id: "debit", header: "مدين", cell: (r) => r.debit },
                      { id: "credit", header: "دائن", cell: (r) => r.credit },
                      { id: "amount", header: "المبلغ", cell: (r) => money(r.amount) },
                      { id: "description", header: "الوصف", cell: (r) => r.description, minTableWidth: 950 },
                    ]}
                    loading={journal.isLoading}
                    fetching={journal.isFetching}
                    error={err(journal.error)}
                    onRetry={() => void journal.refetch()}
                    emptyTitle="لا توجد قيود في الفترة"
                  />
                }
              />
            )}
          </div>
          {tab !== "accounts" && (
            <TablePagination
              className="ps-28"
              page={page}
              totalPages={Math.max(
                1,
                Math.ceil(
                  ((tab === "loans"
                    ? loans.data?.total
                    : tab === "journal"
                      ? journal.data?.total
                      : vouchers.data?.total) || 0) / pageSize,
                ),
              )}
              total={
                (tab === "loans"
                  ? loans.data?.total
                  : tab === "journal"
                    ? journal.data?.total
                    : vouchers.data?.total) || 0
              }
              pageSize={pageSize}
              noun={tab === "loans" ? "عقد" : "سجل"}
              onPage={setPage}
              onPageSize={(n) => {
                setPageSize(n);
                setPage(1);
              }}
            />
          )}
          {(notices.data?.items.length || 0) > 0 && (
            <details className="text-start text-xs text-warning">
              <summary className="cursor-pointer">
                تنبيهات مالية: {notices.data?.items.length} — اضغط لعرضها
              </summary>
              <div className="mt-2 flex max-h-28 flex-wrap gap-2 overflow-auto">
                {notices.data?.items.map((n, i) => (
                  <button
                    key={i}
                    className={secondary}
                    onClick={() => {
                      if (["loan", "voucher", "account"].includes(n.source_type))
                        setSelected({
                          type: n.source_type as "loan" | "voucher" | "account",
                          id: n.source_id,
                        });
                    }}
                  >
                    {n.title} · {money(n.amount)} {n.date ? `· ${n.date}` : ""}
                  </button>
                ))}
              </div>
            </details>
          )}
          <SidePanel
            open={selected !== null}
            title={v?.number || l?.number || a?.name || "تفاصيل العملية"}
            onClose={() => setSelected(null)}
            footer={
              <div className="flex flex-wrap gap-2">
                {selected && caps["finance.print"] && selected.type !== "account" && (
                  <button
                    className={secondary}
                    aria-label="طباعة المستند المالي"
                    onClick={() =>
                      void finora.finance
                        .print(selected.type === "loan" ? "finance_loan" : "finance_voucher", selected.id)
                        .catch((e) => toast.error(toFinoraError(e).message))
                    }
                  >
                    <Printer size={16} />
                  </button>
                )}
                {v && (
                  <>
                    {v.party_id && ["customer", "supplier"].includes(v.party_type) && (
                      <button
                        className={secondary}
                        onClick={() => {
                          setSelected(null);
                          setStatement({
                            type: v.party_type as "customer" | "supplier",
                            id: v.party_id as number,
                          });
                        }}
                      >
                        كشف حساب الجهة
                      </button>
                    )}
                    {v.status === "draft" &&
                      caps["finance.create"] &&
                      meta.data?.categories.some((c) => c.id === v.category) && (
                        <button
                          className={secondary}
                          disabled={!online}
                          onClick={() => {
                            setEditing(v);
                            setEditor("voucher");
                          }}
                        >
                          تعديل المسودة
                        </button>
                      )}
                    {v.status === "draft" && caps["finance.create"] && (
                      <button
                        className={secondary}
                        onClick={() => setOperation({ name: "voucher.submit", row: v })}
                      >
                        طلب اعتماد
                      </button>
                    )}
                    {["draft", "pending"].includes(v.status) && caps["finance.approve"] && (
                      <button
                        className={primary}
                        disabled={!online}
                        onClick={() => setOperation({ name: "voucher.approve", row: v })}
                      >
                        اعتماد وترحيل
                      </button>
                    )}
                    {v.status === "posted" &&
                      !v.source_type?.endsWith("_auto") &&
                      !v.payload?.returned_invoice &&
                      caps["finance.reverse"] && (
                        <button
                          className={secondary}
                          disabled={!online}
                          onClick={() => setOperation({ name: "voucher.reverse", row: v })}
                        >
                          عكس السند
                        </button>
                      )}
                    {v.status === "pending" && caps["finance.approve"] && (
                      <button
                        className={secondary}
                        onClick={() => setOperation({ name: "voucher.reject", row: v })}
                      >
                        رفض
                      </button>
                    )}
                    {v.status === "draft" && caps["finance.create"] && (
                      <button
                        className={secondary}
                        onClick={() => setOperation({ name: "voucher.cancel", row: v })}
                      >
                        إلغاء
                      </button>
                    )}
                  </>
                )}
                {l && caps["finance.loans"] && caps["finance.create"] && (
                  <>
                    {l.status === "draft" && !l.pending_vouchers?.length && (
                      <button
                        className={primary}
                        disabled={!online}
                        onClick={() => setOperation({ name: "loan.fund", row: l })}
                      >
                        تمويل العقد
                      </button>
                    )}
                    {l.status === "active" && (
                      <>
                        <button
                          className={primary}
                          disabled={!online}
                          onClick={() => setOperation({ name: "loan.pay", row: l })}
                        >
                          تسجيل قسط
                        </button>
                        {l.direction === "borrowed" && caps["finance.approve"] && (
                          <button
                            className={secondary}
                            disabled={!online}
                            onClick={() => setOperation({ name: "loan.accrue", row: l })}
                          >
                            استحقاق فائدة
                          </button>
                        )}
                        {l.direction !== "employee" && (
                          <button
                            className={secondary}
                            onClick={() => setOperation({ name: "loan.reschedule", row: l })}
                          >
                            إعادة الجدولة
                          </button>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            }
          >
            {detail.isLoading && <p role="status">جارٍ تحميل التفاصيل…</p>}
            {detail.error && (
              <p role="alert" className="text-danger">
                {err(detail.error)}
              </p>
            )}
            {v && (
              <>
                <DetailRow label="الحالة">
                  <Badge status={v.status} />
                </DetailRow>
                <DetailRow label="المبلغ">{money(v.amount)}</DetailRow>
                <DetailRow label="سبب العملية">{v.category_label}</DetailRow>
                <DetailRow label="الجهة">{v.party_name}</DetailRow>
                <DetailRow label="الحساب">{v.account_name}</DetailRow>
                <DetailRow label="التاريخ">{v.transaction_date}</DetailRow>
                <p className="mt-4 whitespace-pre-wrap text-sm text-ink-soft">{v.notes}</p>
                <h3 className="mt-5 flex items-center gap-2 font-semibold">
                  المستندات المرتبطة
                  {v.allocations?.some((r) => r.type.startsWith("credit_plan_")) && (
                    <FeatureHelp text="حصص الأقساط جزء من سداد المستند، ولا تمثل قبضاً إضافياً. عند عكس السند ترجع حصصه فقط، وتبقى التسديدات الأخرى محفوظة." />
                  )}
                </h3>
                {v.allocations?.map((r, i) => (
                  <DetailRow key={i} label={`${documentLabels[r.type] || "مستند مالي"} #${r.id}`}>
                    <span>
                      {money(r.amount)}
                      <small className="block">
                        قبل: {money(r.before)} · بعد: {money(r.after)}
                      </small>
                    </span>
                  </DetailRow>
                ))}
                {v.journal && (
                  <>
                    <h3 className="mt-5 font-semibold">
                      القيد المحاسبي{" "}
                      <FeatureHelp text="القيود المتوازنة تسجل الأثر مرة واحدة. تحصيل الديون أو أصل القرض لا يعد إيراداً أو مصروفاً جديداً." />
                    </h3>
                    {v.journal.map((j) => (
                      <DetailRow key={j.id} label={`${j.debit} ← ${j.credit}`}>
                        {money(j.amount)}
                      </DetailRow>
                    ))}
                  </>
                )}
                {v.audit?.map((a, i) => (
                  <p className="mt-3 text-xs text-ink-faint" key={i}>
                    {auditLabels[a.action] || "عملية موثقة"} · {formatDateTime(a.at)} · مستخدم #{a.created_by}
                  </p>
                ))}
              </>
            )}
            {l && (
              <>
                <DetailRow label="الجهة">{l.party_name}</DetailRow>
                <DetailRow label="الحالة">
                  <Badge status={l.status} />
                </DetailRow>
                {l.pending_vouchers?.map((p) => (
                  <button
                    key={p.id}
                    className={secondary}
                    onClick={() => setSelected({ type: "voucher", id: p.id })}
                  >
                    طلب اعتماد {p.number} · {money(p.amount)}
                  </button>
                ))}
                <DetailRow label="الأصل المتبقي">{money(l.remaining_principal)}</DetailRow>
                <DetailRow label="الفوائد المتبقية">{money(l.remaining_interest)}</DetailRow>
                <DetailRow label="الرسوم المتبقية">{money(l.remaining_fees)}</DetailRow>
                <DetailRow label="الصافي عند التمويل">{money(l.received_amount)}</DetailRow>
                <h3 className="mt-5 font-semibold">
                  جدول الأقساط{" "}
                  <FeatureHelp text="الأصل والفائدة والرسوم تظهر منفصلة. السداد الجزئي يخفض المتبقي، واستقطاع الراتب لا يحرك الصندوق." />
                </h3>
                {l.schedule?.map((s) => (
                  <div key={s.number} className="mt-3 rounded-control border border-line p-3 text-sm">
                    <div className="flex justify-between">
                      <b>
                        القسط {s.number} · {s.due_date}
                      </b>
                      <Badge status={s.status} />
                    </div>
                    <p className="mt-2 text-xs text-ink-soft">
                      أصل {money(s.principal)} · فائدة {money(s.interest)} · رسوم {money(s.fees)}
                    </p>
                    <p className="mt-2">المتبقي: {money(s.remaining)}</p>
                  </div>
                ))}
                {l.schedule_history?.map((h) => (
                  <details key={h.version} className="mt-4 rounded-control border border-line p-3 text-sm">
                    <summary>الجدولة السابقة · الإصدار {h.version}</summary>
                    {h.rows.map((r) => (
                      <p key={r.number} className="mt-2">
                        القسط {r.number} · {r.due_date} · أصل {money(r.principal)} · فائدة {money(r.interest)}{" "}
                        · رسوم {money(r.fees)}
                      </p>
                    ))}
                  </details>
                ))}
                {l.salary_deductions?.map((r, i) => (
                  <DetailRow key={i} label={`استقطاع مسير راتب #${r.payroll_item_id}`}>
                    {money(r.amount)}
                  </DetailRow>
                ))}
                {l.payments?.map((p, i) => (
                  <DetailRow key={i} label={`قسط ${formatDateTime(p.date)}`}>
                    <button
                      className="text-violet"
                      onClick={() => setSelected({ type: "voucher", id: p.voucher_id })}
                    >
                      سند #{p.voucher_id} · {money(p.principal + p.interest + p.fees)}
                    </button>
                  </DetailRow>
                ))}
              </>
            )}
            {a && (
              <>
                <DetailRow label="الرصيد الحالي">{money(a.balance)}</DetailRow>
                {a.movements.map((r) => (
                  <DetailRow key={r.key} label={`${formatDateTime(r.date)} · ${r.note}`}>
                    <span className={r.amount >= 0 ? "text-success" : "text-danger"}>
                      {money(r.amount)}
                      <small className="block text-ink-faint">رصيد: {money(r.balance_after)}</small>
                    </span>
                  </DetailRow>
                ))}
              </>
            )}
            {selected && selected.type !== "account" && (v || l) && (
              <Attachments
                kind={selected.type}
                id={selected.id}
                rows={(v || l)?.attachments || []}
                canUpload={!!caps["finance.create"] && online}
                onSaved={() => void refresh()}
              />
            )}
          </SidePanel>
          {statement && (
            <PartyStatement
              type={statement.type}
              id={statement.id}
              onClose={() => setStatement(null)}
              onVoucher={(id) => {
                setStatement(null);
                setSelected({ type: "voucher", id });
              }}
            />
          )}
          {editor && meta.data && (
            <FinanceEditor
              mode={editor}
              initialCategory={initialCategory}
              initial={editing || undefined}
              collection={collection || undefined}
              meta={meta.data}
              online={online}
              onClose={() => {
                setInitialCategory(undefined);
                setEditing(null);
                setEditor(null);
                setCollection(null);
              }}
              onSaved={() => {
                setInitialCategory(undefined);
                setEditing(null);
                setEditor(null);
                setCollection(null);
                void refresh();
              }}
            />
          )}
          {operation && (
            <OperationPanel
              operation={operation}
              meta={meta.data}
              online={online}
              onClose={() => setOperation(null)}
              onSaved={() => {
                setOperation(null);
                void refresh();
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

function PartyStatement({
  type,
  id,
  onClose,
  onVoucher,
}: {
  type: "customer" | "supplier";
  id: number;
  onClose(): void;
  onVoucher(id: number): void;
}) {
  useTimeFormat();
  const statement = useQuery({
    queryKey: ["finance", "party-statement", type, id],
    queryFn: () => finora.finance.party(type, id),
  });
  return (
    <SidePanel open title={`كشف حساب ${statement.data?.name || "الجهة"}`} onClose={onClose}>
      <FeatureHelp text="الكشف يعرض المستندات المستحقة والحركات المالية المسجلة. الدين والرصيد المقدم يظهران منفصلين؛ اضغط على حركة لفتح سندها." />
      {statement.error && (
        <p role="alert" className="text-danger">
          {toFinoraError(statement.error).message}
        </p>
      )}
      {statement.isLoading && <p role="status">جارٍ تحميل الكشف…</p>}
      <DetailRow label="الدين الحالي">{money(statement.data?.debt || 0)}</DetailRow>
      <DetailRow label="الرصيد المقدم المتاح">{money(statement.data?.credit || 0)}</DetailRow>
      <h3 className="mt-5 font-semibold">المستندات المستحقة</h3>
      {statement.data?.invoices.map((r) => (
        <DetailRow key={r.id} label={`${documentLabels[r.type] || "مستند"} #${r.number}`}>
          {money(r.remaining)}
        </DetailRow>
      ))}
      {statement.data?.invoices.length === 0 && (
        <p className="text-xs text-ink-soft">لا توجد فواتير مستحقة</p>
      )}
      <h3 className="mt-5 font-semibold">الحركات المالية</h3>
      {statement.data?.movements?.map((r) => (
        <button
          className={cn(secondary, "mt-2 w-full justify-between")}
          key={r.id}
          onClick={() => onVoucher(r.id)}
        >
          <span>
            {r.number} · {r.transaction_date} · {r.category_label}
          </span>
          <span>
            {money(r.amount)} · {statuses[r.status] || r.status}
          </span>
        </button>
      ))}
    </SidePanel>
  );
}

function LedgerReview({
  from,
  to,
  journal,
  canPrint,
}: {
  from: string;
  to: string;
  journal: ReactNode;
  canPrint: boolean;
}) {
  useTimeFormat();
  const [report, setReport] = useState("journal");
  const operational = [
    "customer-aging",
    "supplier-aging",
    "instalments",
    "employee-advances",
    "reconciliation-differences",
  ].includes(report);
  const operations = useQuery({
    queryKey: ["finance", "operational-report", report, from, to],
    queryFn: () => finora.finance.operationalReport(report, { date_from: from, date_to: to }),
    enabled: operational,
  });
  const trial = useQuery({
    queryKey: ["finance", "trial", report === "balance" ? "" : from, to],
    queryFn: () => finora.finance.trial({ date_from: report === "balance" ? "" : from, date_to: to }),
    enabled: report !== "journal" && report !== "cash" && !operational,
  });
  const flow = useQuery({
    queryKey: ["finance", "flow", from, to],
    queryFn: () => finora.finance.cashFlow({ date_from: from, date_to: to }),
    enabled: report === "cash",
  });
  const allowed = useMemo(
    () =>
      trial.data?.rows.filter((r) =>
        report === "profit"
          ? ["revenue", "expense"].includes(r.type)
          : report === "balance"
            ? ["asset", "liability", "equity"].includes(r.type)
            : true,
      ),
    [trial.data, report],
  );
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="التقرير المحاسبي"
          className={cn(input, "w-48")}
          value={report}
          onChange={(e) => setReport(e.target.value)}
        >
          <option value="journal">القيود</option>
          <option value="trial">ميزان المراجعة</option>
          <option value="profit">الأرباح والخسائر</option>
          <option value="balance">الميزانية العمومية</option>
          <option value="cash">التدفق النقدي</option>
          <option value="customer-aging">أعمار ديون العملاء</option>
          <option value="supplier-aging">أعمار ديون الموردين</option>
          <option value="instalments">الأقساط القادمة والمتأخرة</option>
          <option value="employee-advances">سلف الموظفين</option>
          <option value="reconciliation-differences">التسويات والفروقات</option>
        </select>
        <FeatureHelp text="ميزان المراجعة يعرض القيود المتوازنة. الربح يختلف عن النقد؛ أصل القروض وتحويلات الحسابات لا تدخل في الربح. الميزانية تعرض الأرصدة المتراكمة حتى تاريخ النهاية." />
        {canPrint && report !== "journal" && (
          <button
            className={secondary}
            onClick={() =>
              void finora.finance
                .printReport(
                  operational
                    ? (report as Parameters<typeof finora.finance.printReport>[0])
                    : (
                        {
                          trial: "trial-balance",
                          profit: "profit-loss",
                          balance: "balance-sheet",
                          cash: "cash-flow",
                        } as const
                      )[report as "trial" | "profit" | "balance" | "cash"],
                  report === "balance" ? "" : from,
                  to,
                )
                .catch((e) => toast.error(toFinoraError(e).message))
            }
          >
            <Printer size={16} />
            <span className="sr-only">طباعة التقرير</span>
          </button>
        )}
        {trial.data && !trial.data.opening_migration_complete && (
          <span className="text-xs text-warning">راجع الأرصدة الافتتاحية قبل اعتماد تقرير شامل للشركة.</span>
        )}
      </div>
      {operational && (
        <p className="text-xs text-ink-soft">
          {operations.data?.note} · الإجمالي {money(operations.data?.total || 0)}
        </p>
      )}
      {report === "profit" && (
        <p className="text-sm font-semibold">
          الإيراد {money(trial.data?.revenue || 0)} · المصروف {money(trial.data?.expenses || 0)} · صافي الربح{" "}
          {money(trial.data?.profit || 0)}
        </p>
      )}
      {report === "balance" && (
        <p className="text-sm">
          الأصول {money(trial.data?.assets || 0)} · الالتزامات {money(trial.data?.liabilities || 0)} · الحقوق{" "}
          {money(trial.data?.equity || 0)} · الربح المتراكم {money(trial.data?.profit || 0)}
        </p>
      )}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {report === "journal" ? (
          journal
        ) : operational ? (
          <DataTable
            label="تقرير المستحقات"
            rows={operations.data?.rows.map((row, index) => ({
              ...row,
              id: index + 1,
              reference_key: row.id,
            }))}
            columns={[
              { id: "name", header: "الجهة", cell: (r) => r.name },
              { id: "reference", header: "المستند", cell: (r) => r.reference },
              { id: "date", header: "التاريخ", cell: (r) => r.date },
              { id: "status", header: "الحالة / العمر", cell: (r) => r.status },
              { id: "amount", header: "المبلغ", cell: (r) => money(r.amount) },
            ]}
            loading={operations.isLoading}
            fetching={operations.isFetching}
            error={operations.error ? toFinoraError(operations.error).message : null}
            onRetry={() => void operations.refetch()}
            emptyTitle="لا توجد مستحقات في التصفية الحالية"
          />
        ) : report === "cash" ? (
          <DataTable
            label="التدفق النقدي"
            rows={
              flow.data
                ? Object.entries(flow.data.activities).map(([key, value], i) => ({
                    id: i + 1,
                    name: { operating: "تشغيلي", investing: "استثماري", financing: "تمويلي" }[key] || key,
                    ...value,
                  }))
                : undefined
            }
            columns={[
              { id: "name", header: "النشاط", cell: (r) => r.name },
              { id: "in", header: "النقد الداخل", cell: (r) => money(r.in) },
              { id: "out", header: "النقد الخارج", cell: (r) => money(r.out) },
              { id: "net", header: "الصافي", cell: (r) => money(r.net) },
            ]}
            loading={flow.isLoading}
            fetching={flow.isFetching}
            error={flow.error ? toFinoraError(flow.error).message : null}
            onRetry={() => void flow.refetch()}
            emptyTitle="لا توجد حركات نقدية"
          />
        ) : (
          <DataTable
            label="التقرير المحاسبي"
            rows={allowed}
            columns={[
              { id: "code", header: "الرمز", cell: (r) => r.code },
              { id: "name", header: "الحساب", cell: (r) => r.name },
              { id: "debit", header: "مدين", cell: (r) => money(r.debit) },
              { id: "credit", header: "دائن", cell: (r) => money(r.credit) },
              { id: "balance", header: "الرصيد", cell: (r) => <b>{money(r.balance)}</b> },
            ]}
            loading={trial.isLoading}
            fetching={trial.isFetching}
            error={trial.error ? toFinoraError(trial.error).message : null}
            onRetry={() => void trial.refetch()}
            emptyTitle="لا توجد قيود في الفترة"
          />
        )}
      </div>
    </div>
  );
}

function Attachments({
  kind,
  id,
  rows,
  canUpload,
  onSaved,
}: {
  kind: "voucher" | "loan";
  id: number;
  rows: { id: number; filename: string }[];
  canUpload: boolean;
  onSaved(): void;
}) {
  useTimeFormat();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const download = async (id: number) => {
    try {
      const data = await finora.finance.attachment(id);
      if (!data) throw Error("تعذر تحميل المرفق");
      const bytes = Uint8Array.from(atob(data.content), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: data.mime }));
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(toFinoraError(e).message);
    }
  };
  return (
    <section className="mt-5 grid gap-3">
      <h3 className="font-semibold">
        المرفقات{" "}
        <FeatureHelp text="أرفق الإثبات أو العقد بصيغة PDF أو صورة. المرفقات خاصة بالشركة وبصلاحية الوصول إلى السند." />
      </h3>
      {rows.map((r) => (
        <button className={secondary} key={r.id} onClick={() => void download(r.id)}>
          {r.filename}
        </button>
      ))}
      {canUpload && (
        <Field label="إضافة إثبات (حتى 8 ميغابايت)">
          <input
            type="file"
            accept="application/pdf,image/png,image/jpeg"
            disabled={busy}
            className="text-xs"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              void (async () => {
                setBusy(true);
                setError("");
                try {
                  await finora.finance.upload(kind, id, file);
                  onSaved();
                } catch (error) {
                  setError(toFinoraError(error).message);
                } finally {
                  setBusy(false);
                }
              })();
            }}
          />
        </Field>
      )}
      {busy && (
        <p role="status" className="text-xs text-ink-soft">
          جارٍ حفظ المرفق…
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </section>
  );
}

function FinanceEditor({
  initialCategory,
  initial,
  collection,
  mode,
  meta,
  online,
  onClose,
  onSaved,
}: {
  initialCategory?: string;
  initial?: FinanceVoucher;
  collection?: CustomerCollection;
  mode: "voucher" | "loan" | "settings" | "reconciliation";
  meta: FinanceMeta;
  online: boolean;
  onClose(): void;
  onSaved(): void;
}) {
  useTimeFormat();
  const [form, setForm] = useState<Record<string, string>>({
    category: initialCategory ?? "expense",
    direction: "borrowed",
    amount: "",
    principal: "",
    interest: "0",
    fees: "0",
    upfront_fee: "0",
    instalments: "12",
    first_due: isoToday(),
    transaction_date: isoToday(),
    starts_on: isoToday(),
    treasury_account_id: String(meta.accounts[0]?.id || ""),
    branch_id: String(meta.accounts[0]?.branch_id || meta.branches[0]?.id || ""),
    party_name: "",
    intent: "draft",
    notes: "",
    allocations: "",
    ...(collection
      ? {
          category: "customer_payment",
          party_id: String(collection.customerId),
          party_name: collection.customerName,
          allocation_id: `${collection.documentKind === "credit_plan" ? "debt:" : ""}${collection.invoiceId}`,
          amount: String(collection.remaining),
          branch_id: String(collection.branchId || meta.branches[0]?.id || ""),
          treasury_account_id: String(
            meta.accounts.find(
              (account) => account.branch_id === collection.branchId || account.branch_id === null,
            )?.id || "",
          ),
        }
      : {}),
    ...(initial?.payload
      ? Object.fromEntries(
          Object.entries(initial.payload)
            .filter(([, value]) => typeof value === "string" || typeof value === "number")
            .map(([k, v]) => [k, String(v)]),
        )
      : {}),
    ...(initial
      ? {
          amount: String(initial.amount),
          party_name: initial.party_name,
          category: initial.category,
          transaction_date: initial.transaction_date,
          notes: initial.notes,
          intent: "draft",
        }
      : {}),
  });
  useAssistantDraftFields(
    "receipt",
    mode === "voucher" && !initial && !collection && initialCategory === "customer_payment",
    (fields) => {
      setForm((current) => ({
        ...current,
        amount: fields.amount === undefined ? (current.amount ?? "") : String(fields.amount),
        notes: typeof fields.note === "string" ? fields.note : (current.notes ?? ""),
      }));
    },
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const set = (name: string, value: string) => {
    setForm((f) => ({
      ...f,
      [name]: value,
      ...(["category", "party_id"].includes(name) ? { apply_credit: "0", allocation_id: "" } : {}),
    }));
    setKey(crypto.randomUUID());
  };
  const cat = meta.categories.find((c) => c.id === form.category);
  const type = mode === "loan" ? (form.direction === "employee" ? "employee" : "other") : cat?.party_type;
  const parties = useQuery({
    queryKey: ["finance", "parties", type, form.party_search],
    queryFn: () => finora.finance.parties(type || "customer", form.party_search || ""),
    enabled: !collection && ["customer", "supplier", "employee", "loan"].includes(type || ""),
  });
  const party = useQuery({
    queryKey: ["finance", "party", type, form.party_id],
    queryFn: () => finora.finance.party(type || "customer", Number(form.party_id)),
    enabled: ["customer", "supplier"].includes(type || "") && !!form.party_id,
  });
  const textField = (name: string, label: string, t = "text", help?: string) => (
    <Field label={label} help={help}>
      <input
        className={input}
        type={t}
        min={t === "number" ? "0" : undefined}
        step={t === "number" ? "1" : undefined}
        value={form[name] || ""}
        onChange={(e) => set(name, e.target.value)}
      />
    </Field>
  );
  const choose = (name: string, label: string, rows: { id: string | number; name: string }[]) => (
    <Field label={label}>
      <select className={input} value={form[name] || ""} onChange={(e) => set(name, e.target.value)}>
        <option value="">اختر…</option>
        {rows.map((r) => (
          <option value={r.id} key={r.id}>
            {r.name}
          </option>
        ))}
      </select>
    </Field>
  );
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const values: Record<string, unknown> = { ...(initial?.payload || {}), ...form };
      if (initial?.payload?.allocations && !form.allocation_id)
        values.allocations = initial.payload.allocations;
      if (mode === "voucher") {
        if (form.allocation_id)
          values.allocations = [
            {
              [type === "supplier"
                ? "purchase_id"
                : form.allocation_id.startsWith("debt:")
                  ? "plan_id"
                  : "invoice_id"]: Number(form.allocation_id.replace(/^debt:/, "")),
              amount: Number(form.amount),
            },
          ];
        if (form.apply_credit === "1") {
          values.party_type = type;
          await finora.finance.voucherCommand("credit.apply", values, key);
        } else {
          const saved = await finora.finance.voucherCommand(
            initial ? "voucher.edit" : "voucher.create",
            initial ? { ...values, id: initial.id, version: initial.version } : values,
            key,
          );
          if (saved?.status === "local_pending")
            toast.success("حُفظت مسودة محلية بدون أثر مالي؛ تظهر في قائمة المزامنة");
        }
      } else if (mode === "loan") {
        values.person_id = form.party_id;
        values.party_name =
          parties.data?.items.find((p) => String(p.id) === form.party_id)?.name || form.party_name;
        await finora.finance.loanCommand("loan.create", values, key);
      } else if (mode === "reconciliation") {
        values.lines = (form.statement || "")
          .split(/\r?\n/)
          .filter(Boolean)
          .map((line, i) => {
            const [date, amount, ...reference] = line.split(",");
            if (!date || !amount) throw Error(`تحقق من السطر ${i + 1}`);
            return { date: date.trim(), amount: amount.trim(), reference: reference.join(",").trim() };
          });
        await finora.finance.command("reconciliation.create", values, key);
      }
      onSaved();
      toast.success("تم حفظ العملية");
    } catch (e) {
      setError(toFinoraError(e).message);
    } finally {
      setBusy(false);
    }
  };
  if (mode === "settings") return <SettingsPanel meta={meta} onClose={onClose} onSaved={onSaved} />;
  return (
    <SidePanel
      open
      title={
        mode === "loan"
          ? "عقد سلفة أو قرض"
          : mode === "reconciliation"
            ? "مطابقة كشف مصرفي"
            : collection
              ? `تحصيل ${collection.documentKind === "credit_plan" ? "دين مستقل" : "فاتورة"} #${collection.invoiceId}`
              : initial
                ? "تعديل المسودة"
                : "سند مالي جديد"
      }
      onClose={onClose}
      footer={
        <div className="flex items-center gap-2">
          <button
            className={primary}
            disabled={
              busy ||
              (!!collection && (party.isPending || party.isError)) ||
              (!!initial && !online) ||
              (!online && !(mode === "voucher" && form.intent === "draft" && form.apply_credit !== "1"))
            }
            onClick={() => void save()}
          >
            {busy ? "جارٍ الحفظ…" : "حفظ العملية"}
          </button>
          <button className={secondary} onClick={onClose}>
            إغلاق
          </button>
        </div>
      }
    >
      <div className="grid gap-4">
        {collection && (
          <div className="rounded-panel border border-violet/20 bg-violet-soft p-4">
            <strong className="block text-sm text-ink">{collection.customerName}</strong>
            <DetailRow
              label={collection.documentKind === "credit_plan" ? "الدين المستهدف" : "الفاتورة المستهدفة"}
            >
              #{collection.invoiceId}
            </DetailRow>
            <DetailRow label="المتبقي عند فتح الملف">{money(collection.remaining)}</DetailRow>
            <DetailRow label="فرع العملية">
              {meta.branches.find((branch) => String(branch.id) === form.branch_id)?.name || "—"}
            </DetailRow>
            <div className="mt-2 flex items-center gap-2 text-xs text-ink-soft">
              تحصيل مخصص لهذا المستند
              <FeatureHelp text="يخصص المبلغ لهذا المستند فقط. عند الاعتماد يعاد التحقق من الدين وتتحدث الأقساط دون قبض إضافي. المسودة لا تغير الأرصدة. الدين المستقل السابق يحتاج اعتماداً في مراجعة الأرصدة الافتتاحية؛ تحصيله لا يولّد إيراداً جديداً." />
            </div>
          </div>
        )}
        {collection && textField("amount", "المبلغ بالدينار", "number")}
        <p className="rounded-control bg-violet-soft p-3 text-xs leading-6 text-violet-deep">
          {mode === "loan"
            ? "حفظ العقد لا يحرك النقد. بعد مراجعة الأقساط اختر تمويل العقد."
            : mode === "reconciliation"
              ? "المطابقة تقارن كشف المصرف بحركات الحساب. لا تضيف مبلغاً ولا تغير الرصيد."
              : cat?.help}
        </p>
        {mode === "voucher" &&
          !collection &&
          choose(
            "category",
            "سبب العملية",
            meta.categories
              .filter(
                (c) =>
                  ![
                    "loan_funding",
                    "loan_payment",
                    "loan_collection",
                    "loan_grant",
                    "employee_advance",
                    "employee_return",
                  ].includes(c.id),
              )
              .map((c) => ({ id: c.id, name: c.label })),
          )}
        {mode === "loan" &&
          choose("direction", "نوع العقد", [
            { id: "borrowed", name: "قرض مستلم للشركة" },
            { id: "lent", name: "قرض ممنوح للغير" },
            { id: "employee", name: "سلفة موظف" },
          ])}
        {(mode !== "voucher" || cat?.kind !== "settlement") &&
          choose(
            "treasury_account_id",
            "الصندوق / المصرف / المحفظة",
            meta.accounts
              .filter((account) => !collection || String(account.branch_id) === form.branch_id)
              .map((a) => ({ id: a.id, name: `${a.name} · ${money(a.balance)}` })),
          )}
        {!collection && choose("branch_id", "فرع العملية", meta.branches)}
        {!collection &&
          (["customer", "supplier", "employee", "loan"].includes(type || "") ? (
            <>
              {textField("party_search", "بحث عن الجهة")}
              {choose("party_id", "الجهة", parties.data?.items || [])}
              {parties.error && (
                <p role="alert" className="text-danger">
                  تعذر تحميل الجهات <button onClick={() => void parties.refetch()}>إعادة المحاولة</button>
                </p>
              )}
            </>
          ) : (
            mode !== "reconciliation" &&
            textField("party_name", mode === "loan" ? "اسم الجهة" : "الجهة / عنوان المصروف")
          ))}
        {collection && party.error && (
          <p role="alert" className="text-danger">
            تعذر التحقق من ملف العميل.{" "}
            <button className={secondary} onClick={() => void party.refetch()}>
              إعادة المحاولة
            </button>
          </p>
        )}
        {party.data && (
          <div className="rounded-control border border-line p-3 text-xs">
            المستحق: {money(party.data.debt)} · الرصيد المقدم: {money(party.data.credit)}
            {party.data.credit > 0 && (
              <button
                className={secondary}
                onClick={() => set("apply_credit", form.apply_credit === "1" ? "0" : "1")}
              >
                {form.apply_credit === "1" ? "✓ تسوية الرصيد بدون نقد" : "تطبيق رصيد مقدم بدون نقد"}
              </button>
            )}
            {!collection &&
              choose(
                "allocation_id",
                "تخصيص كامل المبلغ لمستند (اختياري)",
                party.data.invoices.map((i) => ({
                  id: i.type === "customer_debt" ? `debt:${i.id}` : i.id,
                  name: `${i.number} · متبقٍ ${money(i.remaining)}`,
                })),
              )}
            {!collection && (
              <p className="mt-2 text-ink-soft">
                بدون اختيار يوزع على أقدم المستندات. المبلغ الزائد يسجل بسند دفعة مقدمة منفصل.
              </p>
            )}
          </div>
        )}
        {mode === "voucher" && (
          <>
            {!collection && textField("amount", "المبلغ بالدينار", "number")}
            {textField("transaction_date", "تاريخ الحركة", "date")}
            {cat?.kind === "transfer" &&
              choose(
                "target_account_id",
                "الحساب المستلم",
                meta.accounts.filter((a) => String(a.id) !== form.treasury_account_id),
              )}
            {["expense_refund", "accrued_expense"].includes(form.category || "") &&
              textField("expense_id", "رقم المصروف الأصلي", "number")}
            {form.category === "fixed_asset" && (
              <>
                {choose("asset_category_id", "فئة الأصل", meta.asset_categories)}
                {textField("asset_name", "اسم الأصل")}
                {textField("asset_months", "عمر الأصل بالأشهر", "number")}
              </>
            )}
            {choose("intent", "طريقة الحفظ", [
              { id: "draft", name: "مسودة — بدون أثر مالي" },
              ...(!initial ? [{ id: "pending", name: "طلب الاعتماد" }] : []),
              ...(!initial && meta.capabilities["finance.approve"]
                ? [{ id: "post", name: "اعتماد وترحيل الآن" }]
                : []),
            ])}
          </>
        )}
        {mode === "loan" && (
          <>
            {textField(
              "principal",
              "أصل القرض / السلفة",
              "number",
              "هذا هو أصل المبلغ المسترد. أصل القرض لا يدخل في الربح.",
            )}
            {form.direction !== "employee" && (
              <>
                {textField("interest", "إجمالي الفوائد", "number")}
                {textField("fees", "إجمالي رسوم الأقساط", "number")}
                {form.direction === "borrowed" &&
                  textField("upfront_fee", "رسوم تخصم من التمويل مقدماً", "number")}
              </>
            )}
            {textField("instalments", "عدد الأقساط", "number")}
            {textField("starts_on", "تاريخ العقد", "date")}
            {textField("first_due", "أول استحقاق", "date")}
            <p className="rounded-control bg-surface-sunken p-3 text-sm">
              صافي التمويل: {money(Number(form.principal || 0) - Number(form.upfront_fee || 0))}
              <br />
              إجمالي السداد:{" "}
              {money(Number(form.principal || 0) + Number(form.interest || 0) + Number(form.fees || 0))}
            </p>
          </>
        )}
        {mode === "reconciliation" && (
          <>
            {textField("starts_on", "بداية الكشف", "date")}
            {textField("ends_on", "نهاية الكشف", "date")}
            {textField("opening_balance", "الرصيد الافتتاحي", "number")}
            {textField("closing_balance", "رصيد الإقفال", "number")}
            <Field
              label="حركات الكشف"
              help="كل سطر: التاريخ، المبلغ، المرجع. الإيداع موجب والسحب سالب؛ مثال 2026-10-10,-50000,حوالة"
            >
              <textarea
                className={cn(input, "h-36 py-3")}
                value={form.statement || ""}
                onChange={(e) => set("statement", e.target.value)}
              />
            </Field>
            <ReconciliationReview />
          </>
        )}
        <Field label="ملاحظات">
          <textarea
            className={cn(input, "h-24 py-3")}
            value={form.notes || ""}
            onChange={(e) => set("notes", e.target.value)}
          />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
      </div>
    </SidePanel>
  );
}

function ReconciliationReview() {
  useTimeFormat();
  const rows = useQuery({
    queryKey: ["finance", "reconciliations"],
    queryFn: () => finora.finance.reconciliations(),
  });
  const [choices, setChoices] = useState<Record<number, string>>({});
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const match = async (id: number, lineId: number) => {
    setBusy(true);
    setError("");
    try {
      await finora.finance.command("reconciliation.match", {
        id,
        line_id: lineId,
        ledger_key: choices[lineId],
        reason: reasons[lineId],
      });
      await rows.refetch();
    } catch (e) {
      setError(toFinoraError(e).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="grid gap-3">
      <h3 className="font-semibold">الكشوف السابقة والمطابقة اليدوية</h3>
      {rows.error && (
        <p role="alert" className="text-danger">
          {toFinoraError(rows.error).message}
        </p>
      )}
      {rows.data?.items.map((r) => (
        <article key={r.id} className="rounded-control border border-line p-3">
          <div className="flex justify-between text-sm">
            <strong>
              كشف #{r.id} · {r.starts_on} — {r.ends_on}
            </strong>
            <Badge status={r.status} />
          </div>
          <p className="mt-2 text-xs text-ink-soft">فرق الرصيد: {money(r.difference)}</p>
          {r.lines.map((l) => (
            <div key={l.id} className="mt-3 grid gap-2 border-t border-line pt-3 text-xs">
              <span>
                {formatDateTime(l.date)} · {money(l.amount)} · {l.reference}
              </span>
              {l.ledger_key ? (
                <span className="text-success">✓ مطابق</span>
              ) : (
                <>
                  <select
                    aria-label={`حركة الحساب للسطر ${l.id}`}
                    className={input}
                    value={choices[l.id] || ""}
                    onChange={(e) => setChoices((c) => ({ ...c, [l.id]: e.target.value }))}
                  >
                    <option value="">اختر حركة مطابقة للمبلغ…</option>
                    {(r.candidates || [])
                      .filter(
                        (c) => c.amount === l.amount && !r.lines.some((line) => line.ledger_key === c.key),
                      )
                      .map((c) => (
                        <option value={c.key} key={c.key}>
                          {formatDateTime(c.date)} · {c.note}
                        </option>
                      ))}
                  </select>
                  <input
                    aria-label={`سبب المطابقة للسطر ${l.id}`}
                    className={input}
                    placeholder="سبب اختيار الحركة"
                    value={reasons[l.id] || ""}
                    onChange={(e) => setReasons((c) => ({ ...c, [l.id]: e.target.value }))}
                  />
                  <button
                    className={secondary}
                    disabled={busy || !choices[l.id] || !reasons[l.id]?.trim()}
                    onClick={() => void match(r.id, l.id)}
                  >
                    مطابقة السطر
                  </button>
                </>
              )}
            </div>
          ))}
        </article>
      ))}
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
    </section>
  );
}

function OperationPanel({
  operation,
  meta,
  online,
  onClose,
  onSaved,
}: {
  operation: { name: string; row: FinanceVoucher | FinanceLoan };
  meta?: FinanceMeta;
  online: boolean;
  onClose(): void;
  onSaved(): void;
}) {
  useTimeFormat();
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [principal, setPrincipal] = useState("");
  const [interest, setInterest] = useState("0");
  const [fees, setFees] = useState("0");
  const [first, setFirst] = useState(isoToday());
  const [count, setCount] = useState("12");
  const [account, setAccount] = useState(String(operation.row.treasury_account_id || ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const change = (fn: () => void) => {
    fn();
    setKey(crypto.randomUUID());
  };
  const pay = operation.name === "loan.pay";
  const accrue = operation.name === "loan.accrue";
  const reschedule = operation.name === "loan.reschedule";
  const needsReason = ["voucher.reverse", "voucher.reject", "voucher.cancel", "loan.reschedule"].includes(
    operation.name,
  );
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const values: Record<string, unknown> = {
        id: operation.row.id,
        version: operation.row.version,
        reason,
        transaction_date: isoToday(),
        treasury_account_id: account,
        notes: reason,
        intent: meta?.capabilities["finance.approve"] ? "post" : "pending",
      };
      if (pay) {
        values.amount = amount;
        if (principal) {
          values.principal = principal;
          values.interest = interest;
          values.fees = fees;
        }
      }
      if (accrue) values.amount = amount;
      if (reschedule) {
        values.first_due = first;
        values.instalments = count;
      }
      if (operation.name.startsWith("voucher."))
        await finora.finance.voucherCommand(operation.name, values, key);
      else await finora.finance.loanCommand(operation.name, values, key);
      onSaved();
      toast.success("تم تنفيذ العملية");
    } catch (e) {
      setError(toFinoraError(e).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <SidePanel
      open
      title={`مراجعة العملية · ${operation.row.number}`}
      onClose={onClose}
      footer={
        <button
          className={primary}
          disabled={!online || busy || (needsReason && !reason.trim())}
          onClick={() => void save()}
        >
          {busy ? "جارٍ التنفيذ…" : "تأكيد العملية"}
        </button>
      }
    >
      <div className="grid gap-4">
        <p className="rounded-control bg-violet-soft p-3 text-sm leading-7">
          {operation.name === "voucher.reverse"
            ? "يُنشأ سند عكس مرتبط بالأصل. يبقى السند الأصلي محفوظاً، ويعود أثره على الذمم والنقد إذا لم توجد عمليات تابعة."
            : operation.name === "loan.fund"
              ? "هذه العملية تحرك النقد فعلياً وتثبت أصل القرض. تحقق من حساب التمويل والمبلغ قبل التأكيد."
              : "راجع التفاصيل قبل التأكيد. الطلب المتكرر بنفس المعرف لا يكرر العملية."}
        </p>
        {pay && (
          <>
            <Field label="مبلغ القسط">
              <input
                type="number"
                step="1"
                min="1"
                className={input}
                value={amount}
                onChange={(e) => change(() => setAmount(e.target.value))}
              />
            </Field>
            <Field label="الحساب">
              <select
                className={input}
                value={account}
                onChange={(e) => change(() => setAccount(e.target.value))}
              >
                {meta?.accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="أصل المبلغ (اختياري)"
              help="تركه فارغاً يوزع القسط تلقائياً حسب الجدول. إذا حددته، مجموع الأصل والفوائد والرسوم يجب أن يساوي مبلغ القسط."
            >
              <input
                type="number"
                min="0"
                className={input}
                value={principal}
                onChange={(e) => change(() => setPrincipal(e.target.value))}
              />
            </Field>
            {principal && (
              <>
                <Field label="الفائدة">
                  <input
                    type="number"
                    min="0"
                    className={input}
                    value={interest}
                    onChange={(e) => change(() => setInterest(e.target.value))}
                  />
                </Field>
                <Field label="الرسوم">
                  <input
                    type="number"
                    min="0"
                    className={input}
                    value={fees}
                    onChange={(e) => change(() => setFees(e.target.value))}
                  />
                </Field>
              </>
            )}
          </>
        )}
        {reschedule && (
          <>
            <Field label="أول استحقاق جديد">
              <input
                type="date"
                className={input}
                value={first}
                onChange={(e) => change(() => setFirst(e.target.value))}
              />
            </Field>
            <Field label="عدد الأقساط الجديدة">
              <input
                type="number"
                min="1"
                max="360"
                className={input}
                value={count}
                onChange={(e) => change(() => setCount(e.target.value))}
              />
            </Field>
          </>
        )}
        {accrue && (
          <Field label="الفائدة المستحقة">
            <input
              type="number"
              min="1"
              step="1"
              className={input}
              value={amount}
              onChange={(e) => change(() => setAmount(e.target.value))}
            />
          </Field>
        )}
        {(needsReason || accrue) && (
          <Field label="سبب العملية">
            <textarea
              className={cn(input, "h-24 py-3")}
              value={reason}
              onChange={(e) => change(() => setReason(e.target.value))}
            />
          </Field>
        )}
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
      </div>
    </SidePanel>
  );
}

function SettingsPanel({ meta, onClose, onSaved }: { meta: FinanceMeta; onClose(): void; onSaved(): void }) {
  useTimeFormat();
  const settings = useQuery({ queryKey: ["finance", "settings"], queryFn: () => finora.finance.settings() });
  const preview = useQuery({ queryKey: ["finance", "migration"], queryFn: () => finora.finance.migration() });
  const [changes, setChanges] = useState<Record<string, boolean | number>>({});
  const [maps, setMaps] = useState<Record<string, number>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [accountName, setAccountName] = useState("");
  const [accountType, setAccountType] = useState("bank");
  const labels: Record<string, string> = {
    allow_negative: "السماح برصيد سالب",
    separate_approval: "المنشئ يختلف عن المعتمد",
    approval_limit: "حد الاعتماد العادي",
    sensitive_threshold: "حد العمليات الحساسة",
    low_balance: "تنبيه انخفاض الرصيد",
    due_warning_days: "أيام التنبيه قبل الاستحقاق",
  };
  const run = async (op: string, payload: Record<string, unknown>) => {
    setBusy(true);
    setError("");
    try {
      await finora.finance.command(op, payload);
      onSaved();
      toast.success("تم حفظ الإعدادات");
    } catch (e) {
      setError(toFinoraError(e).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <SidePanel
      open
      title="إعدادات الحسابات"
      onClose={onClose}
      footer={
        <button
          className={primary}
          disabled={busy || !settings.data}
          onClick={() =>
            void run("settings.save", {
              policy: changes,
              mappings: Object.entries(maps).map(([key, account_id]) => ({ key, account_id })),
            })
          }
        >
          حفظ الإعدادات
        </button>
      }
    >
      <div className="grid gap-4">
        <p className="text-xs leading-6 text-ink-soft">
          السياسات تضبط الاعتماد وحدود المبلغ. تغيير الربط مسموح للحساب بلا رصيد فقط، حتى لا تنفصل أرصدته
          السابقة.
        </p>
        {settings.error && <p role="alert">{toFinoraError(settings.error).message}</p>}
        {Object.entries(labels).map(([key, label]) => {
          const value = changes[key] ?? settings.data?.policy[key] ?? meta.policy[key];
          return (
            <Field key={key} label={label}>
              {typeof value === "boolean" ? (
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-violet"
                  checked={value}
                  onChange={(e) => setChanges((c) => ({ ...c, [key]: e.target.checked }))}
                />
              ) : (
                <input
                  type="number"
                  min="0"
                  step="1"
                  className={input}
                  value={Number(value) || 0}
                  onChange={(e) => setChanges((c) => ({ ...c, [key]: Number(e.target.value) }))}
                />
              )}
            </Field>
          );
        })}
        <h3 className="font-semibold">
          ربط الحسابات المحاسبية{" "}
          <FeatureHelp text="كل نوع حركة يستخدم حساباً من دليل الحسابات الحالي. لا ننشئ دفتر أرصدة منفصلاً." />
        </h3>
        {settings.data?.mappings
          .filter((m) => !m.key.startsWith("treasury:"))
          .map((m) => (
            <Field key={m.key} label={m.name}>
              <select
                className={input}
                value={maps[m.key] ?? m.account_id}
                onChange={(e) => setMaps((c) => ({ ...c, [m.key]: Number(e.target.value) }))}
              >
                {settings.data?.chart
                  .filter((a) => a.type === m.type)
                  .map((a) => (
                    <option value={a.id} key={a.id}>
                      {a.code} · {a.name}
                    </option>
                  ))}
              </select>
            </Field>
          ))}
        <h3 className="mt-3 font-semibold">إضافة حساب نقدي</h3>
        <input
          aria-label="اسم الحساب الجديد"
          className={input}
          value={accountName}
          onChange={(e) => setAccountName(e.target.value)}
          placeholder="اسم المصرف أو الصندوق"
        />
        <select
          aria-label="نوع الحساب الجديد"
          className={input}
          value={accountType}
          onChange={(e) => setAccountType(e.target.value)}
        >
          <option value="bank">مصرف</option>
          <option value="cash">صندوق</option>
          <option value="wallet">محفظة</option>
        </select>
        <button
          className={secondary}
          disabled={busy || !accountName.trim()}
          onClick={() =>
            void run("account.create", {
              name: accountName,
              account_type: accountType,
              branch_id: meta.branches[0]?.id,
            })
          }
        >
          إضافة الحساب
        </button>
        <h3 className="mt-3 font-semibold">مراجعة الأرصدة الافتتاحية</h3>
        <PeriodControls />
        <p className="text-xs leading-6 text-ink-soft">
          راجع الفروقات أولاً. التطبيق يسجل تسوية افتتاحية مرة واحدة ويحفظ العمليات السابقة.
        </p>
        <FeatureHelp text="الفواتير وأقساطها تُحسب مرة واحدة. الدين المستقل يُعتمد بمتبقيه فقط، بدون إعادة قبض الدفعات القديمة أو تسجيل أرباح. إذا سبق اعتماد الافتتاحي، يُعرض اعتماد الديون المستقلة فقط؛ لا تُعاد تسوية الصناديق أو الموردين." />
        {preview.error && (
          <p role="alert" className="text-danger">
            {toFinoraError(preview.error).message}
          </p>
        )}
        {preview.data?.issues?.map((issue, i) => (
          <p role="alert" key={i} className="text-sm text-warning">
            {issue}
          </p>
        ))}
        {preview.data?.rows.map((r) => (
          <DetailRow key={r.key} label={r.name}>
            <span>
              {money(r.target)}
              <small className="block">فرق: {money(r.difference)}</small>
            </span>
          </DetailRow>
        ))}
        {preview.data && (!preview.data.complete || preview.data.debt_upgrade_required) && (
          <button
            className={secondary}
            disabled={busy || !!preview.data?.issues?.length}
            onClick={() =>
              void run("migration.apply", {
                preview_hash: preview.data?.hash,
                reason: preview.data?.debt_upgrade_required
                  ? "اعتماد الديون المستقلة بعد مراجعة الفروقات"
                  : "اعتماد الأرصدة بعد مراجعة الفروقات",
              })
            }
          >
            {preview.data.debt_upgrade_required
              ? "اعتماد الديون المستقلة المعروضة"
              : "اعتماد الأرصدة المعروضة"}
          </button>
        )}
        {preview.data?.complete && !preview.data.debt_upgrade_required && (
          <p className="text-success">تم اعتماد الأرصدة الافتتاحية</p>
        )}
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
      </div>
    </SidePanel>
  );
}

function PeriodControls() {
  useTimeFormat();
  const [period, setPeriod] = useState(isoToday().slice(0, 7));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const run = async (operation: string) => {
    setBusy(true);
    setMessage("");
    try {
      const [year, month] = period.split("-");
      await finora.finance.command(operation, { year: Number(year), month: Number(month), reason });
      setMessage(operation === "period.close" ? "تم إقفال الفترة" : "تم فتح الفترة");
    } catch (e) {
      setMessage(toFinoraError(e).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="grid gap-3 rounded-control border border-line p-3">
      <h3 className="font-semibold">
        إقفال الفترة{" "}
        <FeatureHelp text="إقفال الشهر يمنع الترحيل أو العكس فيه. راجع السندات المعلقة قبل الإقفال، وفتح الفترة مجدداً يتطلب سبباً محفوظاً في سجل العمليات." />
      </h3>
      <input
        type="month"
        aria-label="الفترة المالية"
        className={input}
        value={period}
        onChange={(e) => setPeriod(e.target.value)}
      />
      <input
        className={input}
        aria-label="سبب إقفال أو فتح الفترة"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="سبب العملية"
      />
      <div className="flex gap-2">
        <button
          className={secondary}
          disabled={busy || !reason.trim()}
          onClick={() => void run("period.close")}
        >
          إقفال الشهر
        </button>
        <button
          className={secondary}
          disabled={busy || !reason.trim()}
          onClick={() => void run("period.reopen")}
        >
          إعادة فتح الشهر
        </button>
      </div>
      {message && (
        <p role="status" className="text-xs text-ink-soft">
          {message}
        </p>
      )}
    </section>
  );
}
