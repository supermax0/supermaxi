import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Archive,
  ArchiveRestore,
  Banknote,
  Building2,
  GitBranch,
  MapPin,
  PackageOpen,
  Pencil,
  Plus,
  ShoppingCart,
  Store,
  UserRound,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { Branch } from "@/api/finora/branches";
import { ConfirmDialog } from "@/components/Dialog";
import { DataTable, type Column } from "@/components/DataTable";
import { StatCard } from "@/components/StatCard";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";
import { Metric, Money, Panel } from "../shipping/shared";
import { BranchForm } from "./BranchForm";
import { CashTransfers } from "./CashTransfers";
import { BranchReport } from "./BranchReport";
import { Distribution } from "./Distribution";
import { ExpensesByBranch } from "./ExpensesByBranch";
import { BranchTeam } from "./Team";

export function BranchesWindow() {
  const active = useWindowManager((s) => s.active === "branches");
  const online = useConnection((s) => s.status === "online");
  const client = useQueryClient();
  const [view, setView] = useState<"branches" | "cash" | "expenses" | "distribution" | "report">("branches");
  const [showArchived, setShowArchived] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Branch | "new" | null>(null);
  const [confirmArchive, setConfirmArchive] = useState<Branch | null>(null);

  const meta = useQuery({
    queryKey: ["branches", "meta"],
    queryFn: () => finora.branches.meta(),
    enabled: active,
    staleTime: 30_000,
  });
  const list = useQuery({
    queryKey: ["branches", "list", showArchived],
    queryFn: () => finora.branches.list(showArchived),
    enabled: active,
  });
  const canManage = meta.data?.can_manage ?? false;
  const canReport = canManage || (meta.data?.can_report ?? false);
  const enabled = meta.data?.multi_branch.enabled ?? false;
  const rows = list.data?.rows ?? [];
  const live = rows.filter((r) => r.is_active);

  const totals = useMemo(() => {
    const sum = (pick: (b: Branch) => number | null | undefined) =>
      live.reduce<number | null>((acc, b) => {
        const v = pick(b);
        return acc === null || v === null || v === undefined ? null : acc + v;
      }, 0);
    return {
      sales: sum((b) => b.stats?.sales_total),
      stock: sum((b) => b.stats?.stock_value),
      cash: sum((b) => b.stats?.cash),
      open: live.reduce((acc, b) => acc + (b.stats?.open_orders ?? 0), 0),
    };
  }, [live]);

  const policy = useMutation({
    mutationFn: (value: boolean) => finora.branches.setTransferPolicy(value),
    onSuccess: async (_res, value) => {
      toast.success(value ? "صار اعتماد التحويل شرطاً قبل الإرسال" : "أُلغي شرط اعتماد التحويل");
      await client.invalidateQueries({ queryKey: ["branches"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const feature = useMutation({
    mutationFn: (value: boolean) => finora.branches.setFeature(value),
    onSuccess: async (_res, value) => {
      toast.success(value ? "فُعّل تعدد الفروع — لم تتغير أي بيانات أو أرصدة" : "أُوقف تعدد الفروع");
      await client.invalidateQueries({ queryKey: ["branches"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const archive = useMutation({
    mutationFn: (input: { id: number; restore: boolean }) =>
      finora.branches.archive(input.id, { restore: input.restore }),
    onSuccess: async (_res, input) => {
      toast.success(input.restore ? "استُعيد الفرع" : "أُرشف الفرع");
      setConfirmArchive(null);
      await client.invalidateQueries({ queryKey: ["branches"] });
    },
    onError: (e: unknown) => {
      setConfirmArchive(null);
      toast.error(toFinoraError(e).message);
    },
  });

  const columns = useMemo<Column<Branch>[]>(
    () => [
      {
        id: "name",
        header: "الفرع",
        width: "24%",
        cell: (b) => (
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-maroon-soft text-maroon">
              <Building2 size={18} />
            </span>
            <div className="min-w-0">
              <p className="truncate font-semibold">
                {b.name}
                {b.is_default && (
                  <span className="ms-2 rounded-full bg-violet-soft px-2 py-0.5 text-[10px] font-semibold text-violet-deep">
                    أساسي
                  </span>
                )}
              </p>
              <p className="ltr-isolate truncate text-right text-[11px] text-ink-faint">
                {b.code} · {b.branch_type_label}
              </p>
            </div>
          </div>
        ),
      },
      {
        id: "place",
        header: "الموقع / المدير",
        width: "18%",
        minTableWidth: 800,
        cell: (b) => (
          <div className="min-w-0 text-[12px]">
            <p className="truncate">{[b.governorate, b.city].filter(Boolean).join(" · ") || "—"}</p>
            <p className="truncate text-ink-faint">{b.manager_name || "بدون مدير"}</p>
          </div>
        ),
      },
      {
        id: "sales",
        header: "المبيعات",
        width: "14%",
        cell: (b) => <Money value={b.stats?.sales_total ?? 0} className="font-semibold" />,
      },
      {
        id: "stock",
        header: "قيمة المخزون",
        width: "14%",
        cell: (b) => <Money value={b.stats?.stock_value ?? 0} />,
      },
      {
        id: "cash",
        header: "رصيد الصندوق",
        width: "14%",
        cell: (b) =>
          b.stats?.cash == null ? (
            <span className="text-ink-faint">غير متاح</span>
          ) : (
            <Money value={b.stats.cash} />
          ),
      },
      {
        id: "open",
        header: "مفتوحة",
        width: "8%",
        minTableWidth: 900,
        cell: (b) => <span className="ltr-isolate">{formatNumber(b.stats?.open_orders ?? 0)}</span>,
      },
      {
        id: "state",
        header: "الحالة",
        width: "8%",
        cell: (b) => (
          <span
            className={cn(
              "rounded-full px-2.5 py-1 text-[11px] font-semibold",
              b.is_active ? "bg-success-soft text-success" : "bg-surface-sunken text-ink-faint",
            )}
          >
            {b.is_active ? "نشط" : "مؤرشف"}
          </span>
        ),
      },
    ],
    [],
  );

  const opened = rows.find((r) => r.id === openId) ?? null;

  return (
    <div className="flex h-full min-h-0 gap-4">
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="mb-4 flex shrink-0 items-center justify-between gap-3">
          <p className="text-[13px] text-ink-soft">
            {enabled ? "إدارة فروع الشركة ومخازنها وصناديقها" : "الشركة تعمل بفرع واحد"}
            {totals.open > 0 && ` · ${formatNumber(totals.open)} طلب مفتوح`}
          </p>
          <div className="flex items-center gap-2">
            {enabled && canManage && view === "branches" && (
              <label className="flex items-center gap-2 text-[12px] text-ink-soft">
                <input
                  type="checkbox"
                  checked={meta.data?.transfer_policy.approval_required ?? false}
                  disabled={policy.isPending || !online}
                  onChange={(e) => policy.mutate(e.target.checked)}
                />
                اشتراط اعتماد التحويل قبل الإرسال
              </label>
            )}
            {enabled && view === "branches" && (
              <label className="flex items-center gap-2 text-[12px] text-ink-soft">
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(e) => setShowArchived(e.target.checked)}
                />
                إظهار المؤرشفة
              </label>
            )}
            {canManage && enabled && view === "branches" && (
              <button
                type="button"
                className={supplierPrimary}
                disabled={!online}
                onClick={() => setEditing("new")}
              >
                <Plus size={17} /> فرع جديد
              </button>
            )}
          </div>
        </div>

        {enabled && (
          <div
            className="mb-4 flex shrink-0 gap-1 rounded-control bg-white/70 p-1 shadow-control"
            role="tablist"
            aria-label="أقسام الفروع"
          >
            {(
              [
                ["branches", "الفروع"],
                ["cash", "التحويلات النقدية"],
                ...(canManage ? ([["expenses", "المصاريف"]] as const) : []),
                ...(canReport ? ([["report", "المقارنة"]] as const) : []),
                ...(canManage ? ([["distribution", "التوزيع الأولي"]] as const) : []),
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={view === id}
                onClick={() => setView(id)}
                className={cn(
                  "h-9 rounded-[11px] px-4 text-[13.5px] font-medium",
                  view === id ? "bg-violet-soft text-violet-deep" : "text-ink-soft hover:text-ink",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        {enabled && view === "report" ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <BranchReport enabled={active} />
          </div>
        ) : enabled && view === "distribution" ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Distribution enabled={active} />
          </div>
        ) : enabled && view === "expenses" ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ExpensesByBranch enabled={active} />
          </div>
        ) : enabled && view === "cash" ? (
          <div className="min-h-0 flex-1">
            <CashTransfers enabled={active} />
          </div>
        ) : (
          <>
            {!enabled && meta.data && (
              <section className="glass mb-4 flex shrink-0 items-center gap-4 rounded-panel p-5">
                <span className="grid h-12 w-12 shrink-0 place-items-center rounded-control bg-violet-soft text-violet-deep">
                  <GitBranch size={22} />
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-bold text-ink">تعدد الفروع غير مفعّل</h3>
                  <p className="mt-1 text-[12px] leading-5 text-ink-soft">
                    كل العمليات تُسجَّل على الفرع الأساسي كما هي اليوم. عند التفعيل تظهر إضافة الفروع ومحدد
                    نطاق العمل في الشريط العلوي. التفعيل وحده لا يغيّر أي رصيد أو ربح أو مخزون.
                  </p>
                </div>
                {canManage ? (
                  <button
                    type="button"
                    className={supplierPrimary}
                    disabled={!online || feature.isPending}
                    onClick={() => feature.mutate(true)}
                  >
                    تفعيل تعدد الفروع
                  </button>
                ) : (
                  <span className="text-[12px] text-ink-faint">التفعيل للمدير العام</span>
                )}
              </section>
            )}

            <div className="mb-4 grid shrink-0 grid-cols-5 gap-3">
              <StatCard
                label="الفروع النشطة"
                value={formatNumber(live.length)}
                icon={Store}
                tone="violet"
                loading={list.isPending}
              />
              <StatCard
                label="مبيعات الشركة"
                value={totals.sales === null ? "—" : formatNumber(totals.sales)}
                unit="د.ع"
                icon={ShoppingCart}
                tone="azure"
                loading={list.isPending}
              />
              <StatCard
                label="قيمة المخزون"
                value={totals.stock === null ? "—" : formatNumber(totals.stock)}
                unit="د.ع"
                icon={PackageOpen}
                tone="warning"
                loading={list.isPending}
              />
              <StatCard
                label="إجمالي النقد"
                value={totals.cash === null ? "غير متاح" : formatNumber(totals.cash)}
                unit={totals.cash === null ? undefined : "د.ع"}
                icon={Banknote}
                tone="success"
                loading={list.isPending}
              />
              <StatCard
                label={`تحويلات معلقة · نقد ${formatNumber(list.data?.pending_transfers?.cash ?? 0)} · مخزون ${formatNumber(list.data?.pending_transfers?.stock ?? 0)}`}
                value={formatNumber(
                  (list.data?.pending_transfers?.cash ?? 0) + (list.data?.pending_transfers?.stock ?? 0),
                )}
                unit="تحويل"
                icon={ArrowLeftRight}
                tone="neutral"
                loading={list.isPending}
                onClick={enabled ? () => setView("cash") : undefined}
              />
            </div>

            <DataTable
              label="الفروع"
              columns={columns}
              rows={rows}
              loading={list.isPending}
              fetching={list.isFetching}
              error={list.error ? toFinoraError(list.error).message : null}
              onRetry={() => void list.refetch()}
              emptyTitle="لا توجد فروع"
              activeId={openId}
              onOpen={(b) => setOpenId(b.id)}
            />
          </>
        )}
      </main>

      {opened && view === "branches" && (
        <aside
          aria-label="تفاصيل الفرع"
          className="glass flex w-[380px] shrink-0 flex-col gap-4 overflow-y-auto rounded-panel p-5"
        >
          <header className="flex items-start gap-3">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-control bg-maroon-soft text-maroon">
              <Building2 size={22} />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="truncate text-base font-bold text-ink">{opened.name}</h3>
              <p className="ltr-isolate text-right text-[12px] text-ink-faint">
                {opened.code} · {opened.branch_type_label}
              </p>
            </div>
            <button
              type="button"
              aria-label="إغلاق التفاصيل"
              className="text-ink-faint hover:text-ink"
              onClick={() => setOpenId(null)}
            >
              <X size={18} />
            </button>
          </header>

          <div className="grid grid-cols-2 gap-2">
            <Metric label="المبيعات" value={<Money value={opened.stats?.sales_total ?? 0} />} />
            <Metric label="قيمة المخزون" value={<Money value={opened.stats?.stock_value ?? 0} />} />
            <Metric
              label="رصيد الصندوق"
              value={opened.stats?.cash == null ? "غير متاح" : <Money value={opened.stats.cash} />}
            />
            <Metric label="طلبات مفتوحة" value={formatNumber(opened.stats?.open_orders ?? 0)} />
            {(opened.stats?.in_transit_value ?? 0) > 0 && (
              <Metric
                label="بضاعة بالطريق (ملك الفرع)"
                value={<Money value={opened.stats?.in_transit_value ?? 0} />}
              />
            )}
          </div>

          <Panel title="بيانات الفرع" icon={MapPin} className="shrink-0">
            <dl className="space-y-2 text-[13px]">
              <Row label="الموقع" value={[opened.governorate, opened.city].filter(Boolean).join(" · ")} />
              <Row label="العنوان" value={opened.address} />
              <Row label="الهاتف" value={opened.phone} ltr />
              <Row label="البريد" value={opened.email} ltr />
              <Row label="المدير" value={opened.manager_name} icon={<UserRound size={13} />} />
              <Row label="بدء التشغيل" value={opened.opened_on} ltr />
              <Row label="آخر نشاط" value={opened.stats?.last_activity ?? ""} ltr />
              {!opened.is_active && (
                <Row label="الأرشفة" value={`${opened.archived_at} ${opened.archive_reason}`.trim()} />
              )}
            </dl>
          </Panel>

          <BranchTeam branchId={opened.id} canManage={canManage && opened.is_active} active={active} />

          {canManage && (
            <div className="mt-auto flex flex-wrap gap-2">
              <button
                type="button"
                className={supplierSecondary}
                disabled={!online}
                onClick={() => setEditing(opened)}
              >
                <Pencil size={15} /> تعديل
              </button>
              {opened.is_active ? (
                <button
                  type="button"
                  className={supplierSecondary}
                  disabled={!online || opened.is_default}
                  title={opened.is_default ? "لا تُؤرشف الفرع الأساسي" : undefined}
                  onClick={() => setConfirmArchive(opened)}
                >
                  <Archive size={15} /> أرشفة
                </button>
              ) : (
                <button
                  type="button"
                  className={supplierSecondary}
                  disabled={!online || archive.isPending}
                  onClick={() => archive.mutate({ id: opened.id, restore: true })}
                >
                  <ArchiveRestore size={15} /> استعادة
                </button>
              )}
            </div>
          )}
        </aside>
      )}

      {editing && meta.data && (
        <BranchForm
          branch={editing === "new" ? null : editing}
          types={meta.data.types}
          onClose={() => setEditing(null)}
          onSaved={(b) => {
            setEditing(null);
            setOpenId(b.id);
          }}
        />
      )}
      <ConfirmDialog
        open={confirmArchive !== null}
        title="أرشفة الفرع"
        busy={archive.isPending}
        message={
          <>
            سيُخفى الفرع <strong>{confirmArchive?.name}</strong> من القوائم ومحدد النطاق، وتبقى كل حركاته
            وسجلاته. يرفض النظام الأرشفة إن كان فيه مخزون أو طلبات مفتوحة أو تحويلات معلقة.
          </>
        }
        confirmLabel="أرشفة"
        tone="danger"
        onClose={() => setConfirmArchive(null)}
        onConfirm={() => confirmArchive && archive.mutate({ id: confirmArchive.id, restore: false })}
      />
    </div>
  );
}

function Row({
  label,
  value,
  ltr,
  icon,
}: {
  label: string;
  value: string;
  ltr?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="flex shrink-0 items-center gap-1 text-ink-faint">
        {icon}
        {label}
      </dt>
      <dd className={cn("min-w-0 truncate text-ink", ltr && "ltr-isolate")}>{value || "—"}</dd>
    </div>
  );
}
