import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  CalendarDays,
  CalendarRange,
  CheckCircle2,
  Clock3,
  Download,
  MoreHorizontal,
  PieChart,
  Plus,
  Receipt,
  RefreshCw,
  Repeat,
  Trash2,
  Wallet,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { EXPENSE_TABS, type ExpenseRow, type ExpenseTab, type ExpensesQuery } from "@/api/finora/expenses";
import { DataTable, type Column } from "@/components/DataTable";
import { ConfirmDialog } from "@/components/Dialog";
import { DateInput, Field, FilterPanel, SelectInput } from "@/components/FilterPanel";
import { Menu } from "@/components/Menu";
import { SearchBox } from "@/components/SearchBox";
import { StatCard } from "@/components/StatCard";
import { StatusTabs } from "@/components/StatusTabs";
import { TablePagination } from "@/components/TablePagination";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useConnection } from "@/stores/connection";
import { useCan } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";
import { ExpenseComposer } from "./ExpenseComposer";

const TAB_LABELS: Record<ExpenseTab, string> = { all: "الكل", posted: "مخصومة", scheduled: "مجدولة" };
const BAR_COLORS = ["bg-violet", "bg-maroon", "bg-azure", "bg-cyan", "bg-warning", "bg-success"];

function exportRows(rows: ExpenseRow[]) {
  const cell = (value: string | number) => {
    const raw = String(value);
    const safe = /^[=+\-@\t\r\n]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  const content = [
    ["التاريخ", "الساعة", "المصروف", "الفئة", "المبلغ", "الحساب", "الحالة", "ملاحظة"],
    ...rows.map((r) => [
      r.expense_date ?? "",
      r.post_time,
      r.title,
      r.category_label,
      r.amount,
      r.treasury_account_name,
      r.status === "posted" ? "مخصوم" : "مجدول",
      r.base_note,
    ]),
  ]
    .map((line) => line.map(cell).join(","))
    .join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿", content], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "FINORA-expenses.csv";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ExpensesWindow() {
  const active = useWindowManager((s) => s.active === "expenses");
  const allowed = useCan("view_expenses");
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const [tab, setTab] = useState<ExpenseTab>("all");
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 250);
  const [category, setCategory] = useState("");
  const [accountId, setAccountId] = useState<number | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [draft, setDraft] = useState({ category: "", account: "", from: "", to: "" });
  const [sort, setSort] = useState<ExpensesQuery["sort"]>("date");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [composerOpen, setComposerOpen] = useState(false);
  const [toDelete, setToDelete] = useState<ExpenseRow | null>(null);

  const query = useMemo<ExpensesQuery>(
    () => ({ tab, search, category, treasuryAccountId: accountId, dateFrom, dateTo, sort, page, pageSize }),
    [tab, search, category, accountId, dateFrom, dateTo, sort, page, pageSize],
  );
  const meta = useQuery({
    queryKey: ["expenses", "meta"],
    queryFn: () => finora.expenses.meta(),
    enabled: active && allowed,
    staleTime: 60_000,
  });
  const list = useQuery({
    queryKey: ["expenses", "page", query],
    queryFn: () => finora.expenses.list(query),
    enabled: active && allowed,
  });
  const remove = useMutation({
    mutationFn: (id: number) => finora.expenses.remove(id),
    onSuccess: async () => {
      toast.success("تم حذف المصروف وإرجاع المبلغ إلى الحساب إن كان قد خُصم.");
      setToDelete(null);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["expenses"] }),
        client.invalidateQueries({ queryKey: ["finance"] }),
        client.invalidateQueries({ queryKey: ["reports"] }),
      ]);
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const resetPage = () => setPage(1);
  const filterCount = [category, accountId, dateFrom || dateTo].filter(Boolean).length;
  const summary = list.data?.summary;
  const loading = list.isPending;
  const breakdown = list.data?.by_category ?? [];
  const breakdownTotal = breakdown.reduce((sum, c) => sum + c.amount, 0);

  const rowActions = useCallback(
    (r: ExpenseRow) => (
      <Menu
        label={`إجراءات ${r.title}`}
        items={[
          {
            id: "delete",
            label: r.is_payroll ? "مصروف راتب — يُعالج من الرواتب" : "حذف المصروف",
            icon: Trash2,
            disabled: !online || r.is_payroll,
            onSelect: () => setToDelete(r),
          },
        ]}
        trigger={(props) => (
          <button
            {...props}
            type="button"
            aria-label={`إجراءات ${r.title}`}
            className="grid h-8 w-8 place-items-center rounded-[10px] border border-line/70 bg-white/75 text-ink-soft hover:bg-violet-soft"
          >
            <MoreHorizontal size={17} />
          </button>
        )}
      />
    ),
    [online],
  );

  const columns = useMemo<Column<ExpenseRow>[]>(
    () => [
      {
        id: "title",
        header: "المصروف",
        width: "30%",
        cell: (r) => (
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-gradient-to-br from-violet-soft to-maroon-soft text-lg">
              {r.category_icon || <Receipt size={19} className="text-ink-soft" />}
            </span>
            <div className="min-w-0">
              <p className="truncate font-semibold">{r.title}</p>
              <p className="mt-0.5 max-w-[240px] truncate text-[11px] text-ink-faint">
                {r.base_note || r.category_label}
              </p>
            </div>
          </div>
        ),
      },
      {
        id: "category",
        header: "الفئة",
        width: "13%",
        minTableWidth: 760,
        cell: (r) => (
          <span className="inline-flex max-w-full items-center truncate rounded-full bg-surface-sunken px-2.5 py-1 text-xs text-ink-soft">
            {r.category_label}
          </span>
        ),
      },
      {
        id: "date",
        header: "التاريخ",
        width: "14%",
        cell: (r) => (
          <div className="ltr-isolate text-right text-[13px]">
            <p className="text-ink">{r.expense_date ?? "—"}</p>
            {r.post_time && <p className="text-[11px] text-ink-faint">{r.post_time}</p>}
          </div>
        ),
      },
      {
        id: "account",
        header: "الحساب",
        width: "14%",
        minTableWidth: 880,
        cell: (r) => (
          <span className="truncate text-[13px] text-ink-soft">{r.treasury_account_name || "—"}</span>
        ),
      },
      {
        id: "amount",
        header: "المبلغ",
        width: "14%",
        cell: (r) => (
          <span className="ltr-isolate text-[15px] font-bold text-ink">
            {formatNumber(r.amount)} <span className="text-[11px] font-medium text-ink-faint">د.ع</span>
          </span>
        ),
      },
      {
        id: "status",
        header: "الحالة",
        width: "15%",
        cell: (r) => (
          <div className="flex flex-col items-start gap-1">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold",
                r.status === "posted" ? "bg-success-soft text-success" : "bg-warning-soft text-warning",
              )}
            >
              {r.status === "posted" ? <CheckCircle2 size={13} /> : <Clock3 size={13} />}
              {r.status === "posted" ? "مخصوم" : "مجدول"}
            </span>
            {r.repeat_total && r.repeat_total > 1 && (
              <span className="inline-flex items-center gap-1 text-[10px] text-ink-faint">
                <Repeat size={11} />
                <span className="ltr-isolate">
                  {r.repeat_index}/{r.repeat_total}
                </span>
              </span>
            )}
          </div>
        ),
      },
    ],
    [],
  );

  if (!allowed) {
    return (
      <div className="grid h-full place-items-center text-center">
        <div>
          <p className="text-lg font-semibold text-ink">لا تملك صلاحية عرض المصاريف</p>
          <p className="mt-1 text-sm text-ink-faint">اطلب من مدير النظام منحك صلاحية «المصاريف».</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 gap-4">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="mb-5 flex shrink-0 items-center justify-between gap-3">
          <p className="text-[13px] text-ink-soft">
            مجموع المصاريف المعروضة{" "}
            <span className="ltr-isolate mx-1 font-bold text-maroon">
              {summary ? formatNumber(summary.filtered_total) : "—"}
            </span>
            د.ع
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className={supplierSecondary}
              disabled={!list.data?.rows.length || list.isFetching}
              onClick={() => exportRows(list.data?.rows ?? [])}
            >
              <Download size={16} />
              تصدير الصفحة
            </button>
            <Menu
              label="إجراءات المصاريف"
              items={[
                {
                  id: "refresh",
                  label: "تحديث المصاريف",
                  icon: RefreshCw,
                  disabled: !online,
                  onSelect: () => void client.invalidateQueries({ queryKey: ["expenses"] }),
                },
              ]}
              trigger={(props) => (
                <button
                  {...props}
                  type="button"
                  className={cn(supplierSecondary, "w-11 px-0")}
                  aria-label="إجراءات المصاريف"
                >
                  <MoreHorizontal size={19} />
                </button>
              )}
            />
            <button
              type="button"
              className={supplierPrimary}
              disabled={!online || !meta.data}
              onClick={() => setComposerOpen(true)}
            >
              <Plus size={17} />
              إضافة مصروف
            </button>
          </div>
        </div>

        <div className="mb-5 grid shrink-0 grid-cols-4 gap-3">
          <StatCard
            label="مصاريف اليوم"
            value={formatNumber(summary?.today_total ?? 0)}
            unit="د.ع"
            icon={CalendarDays}
            tone="danger"
            loading={loading}
          />
          <StatCard
            label="مصاريف هذا الشهر"
            value={formatNumber(summary?.month_total ?? 0)}
            unit="د.ع"
            icon={CalendarRange}
            tone="violet"
            loading={loading}
          />
          <StatCard
            label="مصاريف هذه السنة"
            value={formatNumber(summary?.year_total ?? 0)}
            unit="د.ع"
            icon={Wallet}
            tone="azure"
            loading={loading}
          />
          <StatCard
            label={`مجدولة (${formatNumber(summary?.scheduled_count ?? 0)})`}
            value={formatNumber(summary?.scheduled_total ?? 0)}
            unit="د.ع"
            icon={CalendarClock}
            tone="warning"
            loading={loading}
            active={tab === "scheduled"}
            onClick={() => {
              setTab("scheduled");
              resetPage();
            }}
          />
        </div>

        <div className="mb-4 flex shrink-0 flex-wrap items-center gap-2">
          <SearchBox
            value={searchText}
            onChange={(v) => {
              setSearchText(v);
              resetPage();
            }}
            busy={list.isFetching}
            placeholder="ابحث بعنوان المصروف أو الملاحظة…"
            className="min-w-[220px] flex-1"
          />
          <StatusTabs
            label="حالة المصاريف"
            value={tab}
            tabs={EXPENSE_TABS.map((id) => ({ id, label: TAB_LABELS[id], count: list.data?.counts[id] }))}
            onChange={(value) => {
              setTab(value);
              resetPage();
            }}
          />
          <FilterPanel
            activeCount={filterCount}
            onApply={() => {
              setCategory(draft.category);
              setAccountId(draft.account ? Number(draft.account) : null);
              setDateFrom(draft.from);
              setDateTo(draft.to);
              resetPage();
            }}
            onClear={() => {
              setDraft({ category: "", account: "", from: "", to: "" });
              setCategory("");
              setAccountId(null);
              setDateFrom("");
              setDateTo("");
              resetPage();
            }}
          >
            <Field label="الفئة">
              <SelectInput
                placeholder="كل الفئات"
                value={draft.category}
                onChange={(v) => setDraft((d) => ({ ...d, category: v }))}
                options={(meta.data?.categories ?? []).map((c) => ({
                  value: c.key,
                  label: `${c.icon ?? ""} ${c.label}`.trim(),
                }))}
              />
            </Field>
            <Field label="الحساب">
              <SelectInput
                placeholder="كل الحسابات"
                value={draft.account}
                onChange={(v) => setDraft((d) => ({ ...d, account: v }))}
                options={(meta.data?.treasury_accounts ?? []).map((a) => ({
                  value: String(a.id),
                  label: a.name,
                }))}
              />
            </Field>
            <Field label="من تاريخ">
              <DateInput value={draft.from} onChange={(v) => setDraft((d) => ({ ...d, from: v }))} />
            </Field>
            <Field label="إلى تاريخ">
              <DateInput value={draft.to} onChange={(v) => setDraft((d) => ({ ...d, to: v }))} />
            </Field>
          </FilterPanel>
        </div>

        <div className="mb-3 flex shrink-0 items-center justify-between gap-3 text-[11px] text-ink-faint">
          <span className="inline-flex items-center gap-1.5">
            <Clock3 size={13} />
            المصاريف المجدولة لا تُخصم من الحساب قبل موعدها
          </span>
          <label className="inline-flex items-center gap-2 whitespace-nowrap">
            ترتيب حسب
            <SelectInput
              placeholder="اختر الترتيب"
              value={sort}
              onChange={(v) => {
                setSort((v || "date") as ExpensesQuery["sort"]);
                resetPage();
              }}
              options={[
                { value: "date", label: "الأحدث" },
                { value: "oldest", label: "الأقدم" },
                { value: "amount", label: "الأعلى مبلغاً" },
              ]}
            />
          </label>
        </div>

        <DataTable
          label="المصاريف"
          columns={columns}
          rows={list.data?.rows}
          loading={loading}
          fetching={list.isFetching}
          error={list.error ? toFinoraError(list.error).message : null}
          onRetry={() => void list.refetch()}
          emptyTitle="لا توجد مصاريف"
          emptyHint={
            search || tab !== "all" || filterCount > 0
              ? "جرّب تغيير البحث أو مسح التصفية."
              : "سجّل أول مصروف لتتابع أين تذهب أموال الشركة."
          }
          rowActions={rowActions}
        />
        <TablePagination
          page={list.data?.page ?? page}
          totalPages={list.data?.total_pages ?? 1}
          total={list.data?.total ?? 0}
          pageSize={pageSize}
          noun="مصروف"
          onPage={setPage}
          onPageSize={(v) => {
            setPageSize(v);
            resetPage();
          }}
        />
      </main>

      <aside
        aria-label="توزيع المصاريف حسب الفئة"
        className="glass hidden w-[290px] shrink-0 flex-col rounded-panel p-5 xl:flex"
      >
        <header className="mb-4 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-control bg-violet-soft text-violet-deep">
            <PieChart size={18} />
          </span>
          <div>
            <h3 className="text-sm font-bold text-ink">حسب الفئة</h3>
            <p className="text-[11px] text-ink-faint">للمصاريف المعروضة حالياً</p>
          </div>
        </header>
        {breakdown.length === 0 ? (
          <p className="py-10 text-center text-xs text-ink-faint">
            {loading ? "جارٍ التحميل…" : "لا توجد بيانات"}
          </p>
        ) : (
          <ul className="no-scrollbar -mx-1 flex-1 space-y-1 overflow-y-auto px-1">
            {breakdown.map((c, i) => {
              const share = breakdownTotal > 0 ? Math.round((c.amount / breakdownTotal) * 100) : 0;
              const selected = category === c.key;
              return (
                <li key={c.key}>
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => {
                      const next = selected ? "" : c.key;
                      setCategory(next);
                      setDraft((d) => ({ ...d, category: next }));
                      resetPage();
                    }}
                    className={cn(
                      "w-full rounded-control px-3 py-2.5 text-start transition-colors",
                      selected ? "bg-violet-soft ring-1 ring-violet/20" : "hover:bg-surface-sunken",
                    )}
                  >
                    <span className="flex items-center justify-between gap-2 text-[13px]">
                      <span className="flex min-w-0 items-center gap-1.5 truncate font-medium text-ink">
                        {c.icon && <span aria-hidden>{c.icon}</span>}
                        {c.label}
                      </span>
                      <span className="ltr-isolate shrink-0 text-xs text-ink-faint">{share}%</span>
                    </span>
                    <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                      <span
                        className={cn("block h-full rounded-full", BAR_COLORS[i % BAR_COLORS.length])}
                        style={{ width: `${Math.max(share, 2)}%` }}
                      />
                    </span>
                    <span className="mt-1 flex justify-between text-[11px] text-ink-faint">
                      <span className="ltr-isolate font-semibold text-ink-soft">
                        {formatNumber(c.amount)} د.ع
                      </span>
                      <span>{formatNumber(c.count)} مصروف</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>

      {active && composerOpen && meta.data && (
        <ExpenseComposer meta={meta.data} onClose={() => setComposerOpen(false)} />
      )}
      <ConfirmDialog
        open={active && toDelete !== null}
        title="حذف المصروف"
        tone="danger"
        busy={remove.isPending}
        message={
          <>
            سيُحذف المصروف <strong>{toDelete?.title}</strong> بمبلغ{" "}
            <strong className="ltr-isolate">{formatNumber(toDelete?.amount ?? 0)} د.ع</strong>.
            {toDelete?.status === "posted"
              ? " سيُعاد المبلغ إلى الحساب الذي خُصم منه."
              : " المصروف مجدول ولم يُخصم بعد، فلن تتأثر الحسابات."}
          </>
        }
        confirmLabel="حذف المصروف"
        onClose={() => setToDelete(null)}
        onConfirm={() => toDelete && remove.mutate(toDelete.id)}
      />
    </div>
  );
}
