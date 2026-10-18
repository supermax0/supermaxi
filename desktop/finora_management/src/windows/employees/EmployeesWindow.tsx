import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarDays,
  ChevronDown,
  Coins,
  ContactRound,
  Download,
  Fingerprint,
  Loader2,
  Maximize2,
  Plus,
  UsersRound,
  Wallet,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { HRDetails, HRFilters, HRLookups, HRPerson, HRTab, HRWorkspaceRow } from "@/api/finora/hr";
import { DataTable, type Column } from "@/components/DataTable";
import { IconButton } from "@/components/IconButton";
import { SearchBox } from "@/components/SearchBox";
import { TablePagination } from "@/components/TablePagination";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useSelection } from "@/hooks/useSelection";
import { useSession } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { useOffline } from "@/stores/offline";
import { useWindowManager } from "@/stores/windowManager";
import { useHRNavigation } from "@/stores/hrNavigation";
import { cn } from "@/utils/cn";
import { formatIqd } from "@/utils/money";
import { EmployeeEditor, HRActionDialog, HRCalendarDialog, type HRAction } from "./HRDialogs";
import { HRBadge, hours, hrInput, hrPrimary, hrSecondary, labels, hrToday, hrLocalDateTime } from "./shared";
import { PersonnelResources } from "./PersonnelResources";
import { Recruitment } from "./Recruitment";
import { CommissionSettings } from "./CommissionSettings";
import { HRReportDialog } from "./HRReportDialog";
import { AttendanceRequests } from "./AttendanceRequests";
import { AttendanceCalendar } from "./AttendanceCalendar";
import { ApprovalCenter } from "./ApprovalCenter";
import { FinancialStatement } from "./FinancialStatement";

const tabs: { id: HRTab; label: string; permission: string }[] = [
  { id: "employees", label: "الموظفون", permission: "hr.view" },
  { id: "attendance", label: "الحضور والدوام", permission: "hr.attendance.view" },
  { id: "payroll", label: "الرواتب", permission: "hr.payroll.view" },
  { id: "advances", label: "السلف والعمولات", permission: "hr.advance.view" },
  { id: "leave", label: "الإجازات", permission: "hr.leave.manage" },
  { id: "resources", label: "إدارة الموارد", permission: "hr.resources.manage" },
];
const initialFilters: HRFilters = {
  search: "",
  status: "",
  branch_id: "",
  department_id: "",
  page: 1,
  page_size: 25,
  sort: "name",
};
const options = (rows: { id: number; name: string }[]) =>
  rows.map((r) => ({ value: String(r.id), label: r.name }));
function exportRows(rows: HRPerson[]) {
  const cell = (value: unknown) => {
    const raw = String(value ?? "");
    return `"${(/^[=+\-@\t\r\n]/.test(raw) ? "'" : "") + raw.replace(/"/g, '""')}"`;
  };
  const data = [
    ["الرقم", "الموظف", "القسم", "الوظيفة", "الهاتف", "الفرع", "الحالة"],
    ...rows.map((r) => [
      r.code,
      r.name,
      r.department,
      r.job_title,
      r.phone,
      r.branch,
      labels[r.status] ?? r.status,
    ]),
  ]
    .map((row) => row.map(cell).join(","))
    .join("\r\n");
  const url = URL.createObjectURL(new Blob(["\ufeff", data], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "FINORA-employees.csv";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function Avatar({ name, photo, large = false }: { name: string; photo?: string | null; large?: boolean }) {
  if (photo)
    return (
      <img
        src={photo}
        alt={name}
        className={cn("shrink-0 rounded-full object-cover", large ? "h-20 w-20" : "h-10 w-10")}
      />
    );
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full bg-violet-soft font-semibold text-violet",
        large ? "h-20 w-20 text-2xl" : "h-10 w-10 text-sm",
      )}
    >
      {name
        .split(/\s+/)
        .slice(0, 2)
        .map((s) => s[0])
        .join("")}
    </span>
  );
}

export function EmployeesWindow() {
  const active = useWindowManager((s) => s.active === "employees");
  const permissions = useSession((s) => s.session?.permissions ?? []);
  const can = (permission: string) => (permissions as readonly string[]).includes(permission);
  const online = useConnection((s) => s.status === "online");
  const offlineStatus = useOffline((s) => s.status);
  const [tab, setTab] = useState<HRTab>("employees");
  const [filters, setFilters] = useState(initialFilters);
  const search = useDebouncedValue(filters.search, 250);
  const query = useMemo(() => ({ ...filters, search }), [filters, search]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [compactHeight, setCompactHeight] = useState(() => window.innerHeight <= 800);
  const [summaryOverride, setSummaryOverride] = useState<boolean | null>(null);
  const showSummary = summaryOverride ?? !compactHeight;
  useEffect(() => {
    const resize = () => setCompactHeight(window.innerHeight <= 800);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const [editor, setEditor] = useState<"create" | HRPerson | null>(null);
  const [action, setAction] = useState<HRAction | null>(null);
  const [month, setMonth] = useState(hrToday().slice(0, 7));
  const [attendanceDate, setAttendanceDate] = useState(hrToday());
  const [commissionTab, setCommissionTab] = useState(false);
  const [recruitmentOpen, setRecruitmentOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [correctionsOpen, setCorrectionsOpen] = useState(false);
  const [approvalsOpen, setApprovalsOpen] = useState(false);
  const hrTarget = useHRNavigation((s) => s.target);
  useEffect(() => {
    if (!hrTarget) return;
    setFilters({ ...initialFilters });
    if (hrTarget.tab === "corrections") {
      setTab("attendance");
      setCorrectionsOpen(true);
    }
    if (hrTarget.tab === "recruitment") setRecruitmentOpen(true);
    else if (tabs.some((t) => t.id === hrTarget.tab)) setTab(hrTarget.tab as HRTab);
    if (hrTarget.person_id) setSelectedId(hrTarget.person_id);
    if (hrTarget.month) setMonth(hrTarget.month);
    if (hrTarget.tab === "attendance") setAttendanceDate(hrTarget.date.slice(0, 10));
    useHRNavigation.getState().set(null);
  }, [hrTarget]);
  const selection = useSelection();
  const clearSelection = selection.clear;
  useEffect(
    () => clearSelection(),
    [
      filters.page,
      filters.page_size,
      filters.search,
      filters.status,
      filters.branch_id,
      filters.department_id,
      clearSelection,
    ],
  );
  const directory = useQuery({
    queryKey: ["hr", "page", query],
    queryFn: () => finora.hr.list(query),
    enabled: active,
  });
  const lookups = useQuery({ queryKey: ["hr", "lookups"], queryFn: finora.hr.lookups, enabled: active });
  const overview = useQuery({ queryKey: ["hr", "overview"], queryFn: finora.hr.overview, enabled: active });
  const details = useQuery({
    queryKey: ["hr", "details", selectedId],
    queryFn: () => {
      if (selectedId === null) throw new Error("اختر الموظف");
      return finora.hr.details(selectedId);
    },
    enabled: active && selectedId !== null,
  });
  const workspaceTab = commissionTab && tab === "advances" ? "commissions" : tab;
  const workspace = useQuery({
    queryKey: [
      "hr",
      "workspace",
      workspaceTab,
      filters.branch_id,
      filters.department_id,
      filters.page,
      filters.page_size,
      month,
      attendanceDate,
      search,
      filters.status,
    ],
    queryFn: () =>
      finora.hr.workspace(workspaceTab as Exclude<HRTab, "employees">, {
        page: filters.page,
        page_size: filters.page_size,
        month,
        date: attendanceDate,
        branch_id: filters.branch_id,
        department_id: filters.department_id,
        search,
        status: filters.status,
      }),
    enabled: active && tab !== "employees",
  });
  const patch = (values: Partial<HRFilters>) =>
    setFilters((current) => ({ ...current, ...values, page: values.page ?? 1 }));
  const chooseTab = (value: HRTab) => {
    setTab(value);
    patch({ page: 1 });
  };
  useEffect(() => {
    if (!active || selectedId === null) return;
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector('[aria-modal="true"]')) {
        e.stopPropagation();
        setSelectedId(null);
        setExpanded(false);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [active, selectedId]);
  const tools = lookups.data;
  const bulkAction = (mode: string) => {
    const selected = (directory.data?.rows ?? []).filter((p) => selection.selected.has(p.id));
    if (!tools || !selected.length) return;
    const sameBranch = selected.every((p) => p.branch_id === selected[0]?.branch_id);
    const titles: Record<string, string> = {
      department: "نقل القسم للمحددين",
      branch: "نقل الفرع للمحددين",
      state: "تغيير الحالة للمحددين",
      shift: "تعيين وردية للمحددين",
    };
    const field: HRAction["fields"][number] =
      mode === "department"
        ? {
            name: "department_id",
            label: "القسم",
            numeric: true,
            required: true,
            options: options(
              tools.departments.filter(
                (d) => !d.branch_id || (sameBranch && d.branch_id === selected[0]?.branch_id),
              ),
            ),
          }
        : mode === "branch"
          ? {
              name: "branch_id",
              label: "الفرع",
              numeric: true,
              required: true,
              options: options(tools.branches),
            }
          : mode === "state"
            ? {
                name: "status",
                label: "الحالة",
                required: true,
                options: ["active", "suspended", "leave"].map((value) => ({
                  value,
                  label: labels[value] ?? value,
                })),
              }
            : {
                name: "shift_id",
                label: "الوردية",
                numeric: true,
                required: true,
                options: options(
                  tools.shifts.filter((s) => sameBranch && s.branch_id === selected[0]?.branch_id),
                ),
              };
    setAction({
      title: titles[mode] ?? "إجراء جماعي",
      action: "employee.bulk",
      onlineOnly: true,
      notice: `سيطبق الإجراء على ${selected.length} موظف: ${selected.map((p) => p.name).join("، ")}. راجع القائمة قبل الحفظ؛ أي تعارض يوقف المجموعة كاملة.`,
      payload: { mode, people: selected.map((p) => ({ person_id: p.id, version: p.version })) },
      fields: [
        field,
        ...(mode === "shift"
          ? [
              {
                name: "effective_from",
                label: "تاريخ السريان",
                type: "date" as const,
                initial: hrToday(),
                required: true,
              },
            ]
          : []),
        { name: "reason", label: "سبب الإجراء الجماعي", required: true },
      ],
    });
  };
  const todayPeople = directory.data?.rows ?? [];
  const attendanceAction = (employee?: HRPerson, event: "check_in" | "check_out" = "check_in"): HRAction => ({
    title: event === "check_in" ? "تسجيل حضور" : "تسجيل انصراف",
    action: "attendance.record",
    payload: {
      event,
      occurred_at: new Date().toISOString(),
      ...(employee ? { person_id: employee.id } : {}),
    },
    fields: employee
      ? []
      : [
          {
            name: "person_id",
            label: "الموظف",
            numeric: true,
            options: todayPeople.map((p) => ({ value: String(p.id), label: `${p.name} · ${p.code}` })),
            required: true,
          },
        ],
  });
  const personColumns: Column<HRPerson>[] = [
    {
      id: "person",
      header: "الموظف",
      cell: (row) => (
        <div className="flex items-center gap-3">
          <Avatar name={row.name} photo={row.photo_data} />
          <span>
            <strong className="block text-sm font-semibold">{row.name}</strong>
            <small className="mt-1 block text-xs text-ink-faint">{row.code}</small>
          </span>
        </div>
      ),
    },
    { id: "department", header: "القسم", cell: (row) => row.department || "—", minTableWidth: 760 },
    { id: "job", header: "الوظيفة", cell: (row) => row.job_title || "—", minTableWidth: 1050 },
    ...(can("hr.payroll.view")
      ? [
          {
            id: "salary",
            header: "الأجر الأساسي",
            cell: (row: HRPerson) => (row.salary === undefined ? "—" : formatIqd(row.salary)),
            align: "end" as const,
            minTableWidth: 860,
          },
        ]
      : []),
    {
      id: "attendance",
      header: "دوام اليوم",
      cell: (row) => (row.attendance ? <HRBadge state={row.attendance.state} /> : "—"),
    },
    {
      id: "updated",
      header: "آخر تحديث",
      cell: (row) => (
        <span className="text-xs text-ink-faint">{new Date(row.updated_at).toLocaleDateString("ar-IQ")}</span>
      ),
      minTableWidth: 1180,
    },
    {
      id: "open",
      header: "الإجراء",
      width: "80px",
      cell: (row) => (
        <button
          className="inline-flex items-center gap-2 rounded-control bg-violet-soft/80 px-3 py-2 text-xs font-medium text-violet"
          onClick={(e) => {
            e.stopPropagation();
            setSelectedId(row.id);
          }}
        >
          فتح <ArrowLeft size={13} />
        </button>
      ),
    },
  ];
  const data = tab === "employees" ? directory.data : workspace.data;
  const error = tab === "employees" ? directory.error : workspace.error;
  const retry = () => {
    void (tab === "employees" ? directory.refetch() : workspace.refetch());
  };
  const currentEmployee = details.data?.person;
  const openAdvance = (employee?: HRPerson) =>
    setAction({
      title: "طلب سلفة",
      action: "advance.request",
      payload: employee ? { person_id: employee.id } : {},
      fields: [
        ...(!employee
          ? [
              {
                name: "person_id",
                label: "الموظف",
                numeric: true,
                options: todayPeople.map((p) => ({ value: String(p.id), label: p.name })),
                required: true,
              },
            ]
          : []),
        { name: "amount", label: "مبلغ السلفة (د.ع)", type: "number", required: true },
        { name: "instalments", label: "عدد الأقساط", type: "number", initial: "3", required: true },
        { name: "first_month", label: "شهر أول استقطاع", type: "month", initial: month, required: true },
        { name: "reason", label: "السبب", type: "textarea" },
      ],
    });
  const openLeave = (employee?: HRPerson) =>
    setAction({
      title: "طلب إجازة",
      action: "leave.request",
      payload: employee ? { person_id: employee.id } : {},
      fields: [
        ...(!employee
          ? [
              {
                name: "person_id",
                label: "الموظف",
                numeric: true,
                options: todayPeople.map((p) => ({ value: String(p.id), label: p.name })),
                required: true,
              },
            ]
          : []),
        {
          name: "type_id",
          label: "نوع الإجازة",
          options: options(tools?.leave_types ?? []),
          numeric: true,
          required: true,
        },
        { name: "starts", label: "من", type: "date", initial: attendanceDate, required: true },
        { name: "ends", label: "إلى", type: "date", initial: attendanceDate, required: true },
        { name: "half_day", label: "نصف يوم", type: "checkbox" },
        { name: "reason", label: "السبب", type: "textarea" },
      ],
    });
  const summary = overview.data;
  return (
    <div className="relative flex h-full min-h-0 flex-row-reverse gap-4" dir="rtl">
      <div
        className={cn(
          "flex min-h-0 min-w-0 flex-1 flex-col gap-2",
          expanded && selectedId !== null && "hidden",
        )}
      >
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
          <button
            className={hrSecondary}
            aria-expanded={showSummary}
            aria-controls="hr-workspace-summary"
            onClick={() => setSummaryOverride(!showSummary)}
          >
            ملخص الموظفين
            <ChevronDown
              size={16}
              className={cn(
                "transition-transform motion-reduce:transition-none",
                showSummary && "rotate-180",
              )}
            />
          </button>
          <div className="flex flex-wrap gap-2">
            {[
              "hr.leave.approve",
              "hr.advance.approve",
              "hr.attendance.approve",
              "hr.payroll.review",
              "hr.payroll.approve",
              "hr.recruitment.manage",
            ].some(can) && (
              <button className={hrSecondary} onClick={() => setApprovalsOpen(true)}>
                مركز الموافقات
              </button>
            )}
            {can("hr.recruitment.manage") && (
              <button className={hrSecondary} disabled={!tools} onClick={() => setRecruitmentOpen(true)}>
                طلبات التوظيف
              </button>
            )}
            {can("hr.employees.create") && (
              <button className={hrPrimary} onClick={() => setEditor("create")} disabled={!tools}>
                <Plus size={17} />
                إضافة موظف
              </button>
            )}
            {(can("hr.attendance.record") || can("hr.self")) && (
              <button className={hrSecondary} onClick={() => setAction(attendanceAction())} disabled={!tools}>
                <Fingerprint size={18} />
                تسجيل حضور
              </button>
            )}
            {tab === "employees" && selection.selected.size > 0 && can("hr.reports.view") && (
              <button
                className={hrSecondary}
                onClick={() =>
                  exportRows(
                    (directory.data?.rows ?? []).filter(
                      (p) => !selection.selected.size || selection.selected.has(p.id),
                    ),
                  )
                }
                disabled={!directory.data?.rows.length}
              >
                <Download size={16} />
                تصدير {selection.selected.size ? "المحددين" : "الصفحة"}
              </button>
            )}
            {tab === "employees" && selection.selected.size > 0 && tools && (
              <select
                className={`${hrInput.replace("w-full", "")} w-44`}
                aria-label="إجراء جماعي للمحددين"
                value=""
                disabled={!online}
                onChange={(e) => bulkAction(e.target.value)}
              >
                <option value="">إجراء لـ {selection.selected.size} موظف</option>
                {can("hr.employees.edit") && (
                  <>
                    <option value="department">تغيير القسم</option>
                    <option value="branch">تغيير الفرع</option>
                  </>
                )}
                {can("hr.shifts.manage") && <option value="shift">تعيين وردية</option>}
                {can("hr.employees.state") && <option value="state">تحديث الحالة</option>}
              </select>
            )}
            {can("hr.reports.view") && (
              <button className={hrSecondary} onClick={() => setReportOpen(true)}>
                <Download size={16} />
                طباعة وتصدير
              </button>
            )}
          </div>
        </div>
        {(offlineStatus.operations.some(
          (o) => o.kind === "hr" && o.status !== "done" && o.status !== "cancelled",
        ) ||
          !online) && (
          <p className="rounded-control border border-violet/15 bg-violet-soft/30 px-3 py-2 text-xs leading-6 text-ink-soft">
            {!online && "تُعرض بيانات آخر اتصال بالسيرفر. "}
            {offlineStatus.operations.filter((o) => o.kind === "hr" && o.status === "pending").length > 0 &&
              `${offlineStatus.operations.filter((o) => o.kind === "hr" && o.status === "pending").length} طلب HR محفوظ محلياً وبانتظار التأكيد. `}
            {offlineStatus.operations.some((o) => o.kind === "hr" && o.status === "conflict") &&
              "توجد طلبات تحتاج مراجعة؛ افتح المزامنة من الإعدادات."}
          </p>
        )}
        <div
          id="hr-workspace-summary"
          className={cn("shrink-0 grid-cols-5 gap-3", showSummary ? "grid" : "hidden")}
        >
          {[
            {
              label: "إجمالي الموظفين",
              value: summary?.employees,
              icon: UsersRound,
              tone: "text-azure bg-azure-soft",
              go: () => {
                chooseTab("employees");
                patch({ status: "active" });
              },
            },
            {
              label: "الحاضرون اليوم",
              value: summary ? (summary.attendance.present ?? 0) + (summary.attendance.late ?? 0) : null,
              icon: ContactRound,
              tone: "text-success bg-success-soft",
              go: () => chooseTab("attendance"),
              permission: "hr.attendance.view",
            },
            {
              label: "رواتب الشهر المعتمدة",
              value: summary?.salaries,
              icon: Wallet,
              tone: "text-violet bg-violet-soft",
              go: () => chooseTab("payroll"),
              permission: "hr.payroll.view",
            },
            {
              label: "السلف المتبقية",
              value: summary?.advances,
              icon: Wallet,
              tone: "text-danger bg-danger-soft",
              go: () => {
                setCommissionTab(false);
                chooseTab("advances");
              },
              permission: "hr.advance.view",
            },
            {
              label: "العمولات المستحقة",
              value: summary?.commissions,
              icon: Coins,
              tone: "text-maroon bg-violet-soft",
              go: () => {
                setCommissionTab(true);
                chooseTab("advances");
              },
              permission: "hr.commission.view",
            },
          ].map((card) => (
            <button
              key={card.label}
              className="flex h-16 min-w-0 items-center gap-3 rounded-panel border border-line/80 bg-white/80 px-3 py-2 text-start shadow-control disabled:cursor-default"
              onClick={card.go}
              disabled={!!card.permission && !can(card.permission)}
            >
              <div className="min-w-0 flex-1">
                <span className="block truncate text-[11px] leading-4 text-ink-soft" title={card.label}>
                  {card.label}
                </span>
                <strong
                  className={cn(
                    "block truncate leading-6 text-ink",
                    (card.value?.toLocaleString("en-US").length ?? 0) > 12
                      ? "text-xs"
                      : "text-base xl:text-lg",
                  )}
                >
                  {card.value === null || card.value === undefined ? "—" : card.value.toLocaleString("en-US")}
                </strong>
              </div>
              <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-control ${card.tone}`}>
                <card.icon size={18} />
              </span>
            </button>
          ))}
        </div>
        <div role="tablist" aria-label="الموارد البشرية" className="grid shrink-0 grid-cols-6 gap-2">
          {tabs.map((item, index) => (
            <button
              key={item.id}
              role="tab"
              aria-selected={tab === item.id}
              tabIndex={tab === item.id ? 0 : -1}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                  e.preventDefault();
                  const step = e.key === "ArrowLeft" ? 1 : -1;
                  const next = tabs[(index + step + tabs.length) % tabs.length];
                  if (next && (can(next.permission) || (can("hr.self") && next.id !== "resources")))
                    chooseTab(next.id);
                }
              }}
              className={cn(
                "h-10 rounded-control border text-xs font-medium transition-colors",
                tab === item.id
                  ? "border-violet/60 bg-violet-soft text-violet"
                  : "border-line/70 bg-white/40 text-ink-soft",
              )}
              onClick={() => chooseTab(item.id)}
              disabled={
                !can(item.permission) &&
                !(item.id === "advances" && can("hr.commission.view")) &&
                !(can("hr.self") && item.id !== "resources")
              }
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <SearchBox
            value={filters.search}
            onChange={(value) => patch({ search: value })}
            placeholder="ابحث بالاسم أو الهاتف أو الرقم الوظيفي..."
            className="min-w-[220px] flex-1"
          />
          <details className="relative shrink-0">
            <summary className={`${hrSecondary} cursor-pointer list-none`}>
              تصفية{filters.status || filters.department_id || filters.branch_id ? " •" : ""}
            </summary>
            <div className="absolute start-0 top-full z-20 mt-2 flex w-64 flex-col gap-3 rounded-panel border border-line bg-white p-4 shadow-glass">
              <p className="text-xs text-ink-soft">تصفية الموظفين والسجلات حسب الحالة والقسم والفرع</p>
              <select
                aria-label="الحالة الوظيفية"
                className={hrInput}
                value={filters.status}
                onChange={(e) => patch({ status: e.target.value })}
              >
                <option value="">الحالة: الكل</option>
                {["active", "suspended", "leave", "terminated"].map((s) => (
                  <option key={s} value={s}>
                    {labels[s]}
                  </option>
                ))}
              </select>
              <select
                aria-label="القسم"
                className={hrInput}
                value={filters.department_id}
                onChange={(e) => patch({ department_id: e.target.value })}
              >
                <option value="">القسم: الكل</option>
                {tools?.departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              <select
                aria-label="الفرع"
                className={hrInput}
                value={filters.branch_id}
                onChange={(e) => patch({ branch_id: e.target.value })}
              >
                <option value="">الفروع المتاحة</option>
                {tools?.branches.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
          </details>
          {tab !== "employees" && tools && (
            <WorkspaceTools
              tab={tab}
              commissionTab={commissionTab}
              setCommissionTab={setCommissionTab}
              can={can}
              month={month}
              setMonth={setMonth}
              date={attendanceDate}
              setDate={setAttendanceDate}
              tools={tools}
              setAction={setAction}
              openAdvance={() => openAdvance()}
              openLeave={() => openLeave()}
              openCalendar={() => setCalendarOpen(true)}
              online={online}
            />
          )}
          {tab === "attendance" && (can("hr.attendance.approve") || can("hr.self")) && (
            <button className={hrSecondary} onClick={() => setCorrectionsOpen(true)}>
              طلبات تصحيح الحضور
            </button>
          )}
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {tab === "employees" ? (
            <DataTable
              label="قائمة الموظفين"
              columns={personColumns}
              rows={directory.data?.rows}
              loading={directory.isLoading}
              fetching={directory.isFetching}
              error={error ? toFinoraError(error).message : null}
              onRetry={retry}
              emptyTitle="لا توجد نتائج"
              emptyHint="عدّل البحث أو أضف موظفاً جديداً"
              selection={selection}
              activeId={selectedId}
              onOpen={(row) => setSelectedId(row.id)}
            />
          ) : (
            <WorkspaceTable
              tab={workspaceTab as Exclude<HRTab, "employees"> | "commissions"}
              rows={workspace.data?.rows}
              loading={workspace.isLoading}
              fetching={workspace.isFetching}
              error={error ? toFinoraError(error).message : null}
              onRetry={retry}
              can={can}
              tools={tools}
              setAction={setAction}
              onOpen={setSelectedId}
              online={online}
            />
          )}
        </div>
        <TablePagination
          page={filters.page}
          totalPages={data?.total_pages ?? 1}
          total={data?.total ?? 0}
          pageSize={filters.page_size}
          noun={tab === "employees" ? "موظف" : "سجل"}
          onPage={(page) => patch({ page })}
          onPageSize={(page_size) => patch({ page_size })}
        />
      </div>
      {selectedId !== null && (
        <aside
          className={cn(
            "absolute inset-y-0 start-0 z-30 flex min-h-0 flex-col rounded-panel border border-line/70 bg-white shadow-glass",
            expanded ? "w-full" : "w-[520px] min-w-[340px] max-w-[60%]",
          )}
        >
          <div className="flex items-center justify-between border-b border-line/60 px-4 py-3">
            <div className="flex gap-2">
              <IconButton
                label="إغلاق ملف الموظف"
                onClick={() => {
                  setSelectedId(null);
                  setExpanded(false);
                }}
              >
                <X size={18} />
              </IconButton>
              <IconButton
                label={expanded ? "تصغير الملف" : "توسيع الملف"}
                onClick={() => setExpanded(!expanded)}
              >
                <Maximize2 size={16} />
              </IconButton>
            </div>
            {currentEmployee && can("hr.employees.edit") && (
              <button className={hrSecondary} onClick={() => setEditor(currentEmployee)}>
                تعديل
              </button>
            )}
          </div>
          {details.isLoading ? (
            <div className="grid flex-1 place-items-center">
              <Loader2 className="animate-spin text-violet" />
            </div>
          ) : details.error ? (
            <p role="alert" className="p-5 text-danger">
              {toFinoraError(details.error).message}
            </p>
          ) : details.data && tools ? (
            <EmployeePanel
              details={details.data}
              tools={tools}
              can={can}
              onAction={setAction}
              onAttendance={(event) => setAction(attendanceAction(details.data?.person, event))}
              onAdvance={() => openAdvance(details.data?.person)}
              onLeave={() => openLeave(details.data?.person)}
            />
          ) : null}
        </aside>
      )}
      {editor !== null && tools && (
        <EmployeeEditor
          employee={editor === "create" ? null : editor}
          lookups={tools}
          onClose={() => setEditor(null)}
          onSaved={(id, pending) => {
            setEditor(null);
            if (!pending) setSelectedId(id);
          }}
        />
      )}
      {recruitmentOpen && tools && (
        <Recruitment tools={tools} onClose={() => setRecruitmentOpen(false)} onOpen={setSelectedId} />
      )}
      {reportOpen && (
        <HRReportDialog
          tab={workspaceTab}
          onClose={() => setReportOpen(false)}
          query={{
            period: "this_month",
            month,
            date: attendanceDate,
            ...(search ? { search: search.slice(0, 80) } : {}),
            ...(filters.status ? { status: filters.status } : {}),
            ...(filters.branch_id ? { branch_id: Number(filters.branch_id) } : {}),
            ...(filters.department_id ? { department_id: Number(filters.department_id) } : {}),
          }}
        />
      )}
      {action && (
        <HRActionDialog key={JSON.stringify(action)} action={action} onClose={() => setAction(null)} />
      )}
      {calendarOpen && tools && <HRCalendarDialog tools={tools} onClose={() => setCalendarOpen(false)} />}
      {approvalsOpen && <ApprovalCenter onClose={() => setApprovalsOpen(false)} />}
      {correctionsOpen && (
        <AttendanceRequests
          onClose={() => setCorrectionsOpen(false)}
          onAction={setAction}
          canApprove={can("hr.attendance.approve")}
        />
      )}
    </div>
  );
}

function WorkspaceTools({
  tab,
  commissionTab,
  setCommissionTab,
  can,
  month,
  setMonth,
  date,
  setDate,
  tools,
  setAction,
  openAdvance,
  openLeave,
  openCalendar,
  online,
}: {
  tab: HRTab;
  commissionTab: boolean;
  setCommissionTab(value: boolean): void;
  can(permission: string): boolean;
  month: string;
  setMonth(value: string): void;
  date: string;
  setDate(value: string): void;
  tools: HRLookups;
  setAction(action: HRAction): void;
  openAdvance(): void;
  openLeave(): void;
  openCalendar(): void;
  online: boolean;
}) {
  const branchField = {
    name: "branch_id",
    label: "الفرع",
    numeric: true,
    options: options(tools.branches),
    required: true,
  };
  return (
    <div className="contents">
      {tab === "attendance" && (
        <input
          aria-label="تاريخ الدوام"
          type="date"
          className={`${hrInput.replace("w-full", "")} w-40 shrink-0`}
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      )}
      {["attendance", "resources"].includes(tab) && can("hr.settings.manage") && (
        <button className={hrSecondary} disabled={!online} onClick={openCalendar}>
          <CalendarDays size={16} />
          تقويم العمل
        </button>
      )}
      {tab === "payroll" && (
        <>
          <input
            aria-label="شهر الرواتب"
            type="month"
            className={`${hrInput.replace("w-full", "")} w-40 shrink-0`}
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          />
          {can("hr.payroll.prepare") && (
            <button
              className={hrPrimary}
              disabled={!online}
              onClick={() =>
                setAction({
                  title: "إعداد مسير الرواتب",
                  action: "payroll.prepare",
                  financial: true,
                  fields: [
                    branchField,
                    { name: "month", label: "فترة الرواتب", type: "month", initial: month, required: true },
                  ],
                })
              }
            >
              <Plus size={16} />
              احتساب مسير
            </button>
          )}
        </>
      )}
      {tab === "advances" && (
        <>
          <button
            className={cn(hrSecondary, !commissionTab && "bg-violet-soft text-violet")}
            onClick={() => setCommissionTab(false)}
            disabled={!can("hr.advance.view") && !can("hr.self")}
          >
            السلف
          </button>
          <button
            className={cn(hrSecondary, commissionTab && "bg-violet-soft text-violet")}
            onClick={() => setCommissionTab(true)}
            disabled={!can("hr.commission.view") && !can("hr.self")}
          >
            العمولات
          </button>
          {!commissionTab && can("hr.advance.create") && (
            <button className={hrPrimary} onClick={openAdvance}>
              <Plus size={16} />
              طلب سلفة
            </button>
          )}
        </>
      )}
      {tab === "leave" && (can("hr.leave.manage") || can("hr.self")) && (
        <button className={hrPrimary} onClick={openLeave}>
          <Plus size={16} />
          طلب إجازة
        </button>
      )}
      {tab === "resources" && (
        <>
          {can("hr.shifts.manage") && (
            <button
              className={hrSecondary}
              onClick={() =>
                setAction({
                  title: "إضافة وردية دوام",
                  action: "shift.create",
                  fields: [
                    branchField,
                    { name: "name", label: "اسم الوردية", required: true },
                    { name: "starts", label: "بداية الدوام", type: "time", required: true },
                    { name: "ends", label: "نهاية الدوام", type: "time", required: true },
                    { name: "weekdays", label: "أيام العمل", type: "weekdays", required: true },
                    {
                      name: "break_minutes",
                      label: "الاستراحة بالدقائق",
                      type: "number",
                      initial: "0",
                      required: true,
                    },
                    {
                      name: "grace_minutes",
                      label: "السماح بالدقائق",
                      type: "number",
                      initial: "0",
                      required: true,
                    },
                    { name: "overtime_enabled", label: "احتساب الوقت الإضافي", type: "checkbox" },
                  ],
                })
              }
            >
              إضافة وردية
            </button>
          )}
          {can("hr.resources.manage") && (
            <button
              className={hrSecondary}
              onClick={() =>
                setAction({
                  title: "إضافة قسم",
                  action: "department.create",
                  fields: [branchField, { name: "name", label: "اسم القسم", required: true }],
                })
              }
            >
              إضافة قسم
            </button>
          )}
          {can("hr.settings.manage") && (
            <button
              className={hrSecondary}
              onClick={() =>
                setAction({
                  title: "إعداد نوع إجازة",
                  action: "leave_type.create",
                  fields: [
                    { name: "name", label: "اسم نوع الإجازة", required: true },
                    { name: "paid", label: "إجازة مدفوعة", type: "checkbox", initial: true },
                    {
                      name: "yearly_half_days",
                      label: "الرصيد السنوي بوحدات نصف يوم",
                      type: "number",
                      required: true,
                    },
                  ],
                })
              }
            >
              أنواع الإجازات
            </button>
          )}
        </>
      )}
    </div>
  );
}

export function WorkspaceTable({
  tab,
  rows,
  loading,
  fetching,
  error,
  onRetry,
  can,
  tools,
  setAction,
  onOpen,
  online,
}: {
  tab: Exclude<HRTab, "employees"> | "commissions";
  rows: HRWorkspaceRow[] | undefined;
  loading: boolean;
  fetching: boolean;
  error: string | null;
  onRetry(): void;
  can(permission: string): boolean;
  tools: HRLookups | undefined;
  setAction(action: HRAction): void;
  onOpen(id: number): void;
  online: boolean;
}) {
  type Row = HRWorkspaceRow & { id: number; attendanceId: number | null };
  // Scheduled employees need a table key, but that key is not an attendance record.
  const display = rows?.map((row) => ({ ...row, id: row.id ?? row.person_id, attendanceId: row.id }));
  const columns: Column<Row>[] = [
    {
      id: "employee",
      header: "الموظف",
      cell: (r) => (
        <span>
          <strong className="block font-medium">{r.person_name}</strong>
          <small className="text-ink-faint">{r.code}</small>
        </span>
      ),
    },
  ];
  const money = (
    key: "gross" | "deductions" | "net" | "paid" | "remaining" | "amount" | "repaid",
    header: string,
  ) => columns.push({ id: key, header, cell: (r) => formatIqd(r[key] ?? 0), align: "end" });
  if (tab === "attendance") {
    columns.push(
      { id: "in", header: "الحضور", cell: (r) => r.check_in || "—" },
      { id: "out", header: "الانصراف", cell: (r) => r.check_out || "—" },
      { id: "worked", header: "ساعات العمل", cell: (r) => hours(r.worked_minutes ?? 0) },
      { id: "late", header: "التأخير", cell: (r) => `${r.late_minutes ?? 0} د` },
    );
  } else if (tab === "payroll") {
    money("gross", "الإجمالي");
    money("deductions", "الاستقطاعات");
    money("net", "الصافي");
    money("paid", "المصروف");
    money("remaining", "المتبقي");
  } else if (tab === "advances") {
    money("amount", "السلفة");
    money("repaid", "المسدد");
    money("remaining", "المتبقي");
    columns.push({ id: "instalments", header: "الأقساط", cell: (r) => r.instalments });
  } else if (tab === "commissions") {
    money("amount", "العمولة");
    money("paid", "المصروف");
    money("remaining", "المتبقي");
    columns.push({ id: "invoice", header: "الفاتورة", cell: (r) => `#${r.invoice_id}` });
  } else if (tab === "leave") {
    columns.push(
      { id: "type", header: "الإجازة", cell: (r) => r.type },
      { id: "starts", header: "من", cell: (r) => r.starts },
      { id: "ends", header: "إلى", cell: (r) => r.ends },
      { id: "days", header: "الأيام", cell: (r) => r.days },
    );
  } else {
    columns.push(
      { id: "kind", header: "نوع السجل", cell: (r) => labels[r.kind ?? ""] ?? r.kind },
      { id: "title", header: "التفاصيل", cell: (r) => String(r.detail?.title ?? "") },
    );
  }
  if (tab !== "resources")
    columns.push({
      id: "status",
      header: "الحالة",
      cell: (r) => <HRBadge state={r.state ?? r.status ?? "pending"} />,
    });
  columns.push({
    id: "action",
    header: "الإجراء",
    cell: (row) => {
      const buttons = [];
      if (tab === "commissions") {
        const manage = can("hr.commission.manage");
        const fields = [
          { name: "reason", label: "سبب اعتماد التسوية", required: true },
          {
            name: "first_month",
            label: "بداية استرداد العمولة المصروفة (عند الحاجة)",
            type: "month" as const,
          },
          { name: "instalments", label: "عدد الأقساط", type: "number" as const, numeric: true, initial: "1" },
        ];
        const commissionAction =
          row.source === "change" && manage
            ? {
                title: "اعتماد تسوية عمولة",
                action: "commission.change",
                payload: { change_id: row.entity_id, version: row.version },
                fields,
              }
            : row.source === "legacy" && ["pending", "paid"].includes(row.status ?? "") && manage
              ? {
                  title: "نقل عمولة سابقة للمراجعة",
                  action: "commission.import",
                  payload: { legacy_id: row.entity_id },
                  fields: [],
                }
              : row.source === "hr" && row.status === "pending" && manage
                ? {
                    title: "اعتماد استحقاق العمولة",
                    action: "commission.approve",
                    payload: { commission_id: row.entity_id, version: row.version },
                    fields: [],
                  }
                : row.source === "hr" &&
                    ["approved", "paid"].includes(row.status ?? "") &&
                    (row.remaining ?? 0) > 0 &&
                    !row.has_changes &&
                    can("hr.commission.pay")
                  ? {
                      title: "صرف العمولة",
                      action: "commission.pay",
                      payload: { commission_id: row.entity_id, version: row.version },
                      fields: [
                        {
                          name: "treasury_account_id",
                          label: "الصندوق أو البنك",
                          numeric: true,
                          required: true,
                          options:
                            tools?.treasury_accounts.map((f) => ({ value: String(f.id), label: f.name })) ??
                            [],
                        },
                      ],
                    }
                  : null;
        if (commissionAction)
          buttons.push(
            <button
              key="commission"
              className={hrSecondary}
              disabled={!online}
              onClick={(e) => {
                e.stopPropagation();
                setAction({ ...commissionAction, financial: true });
              }}
            >
              {row.source === "change"
                ? "مراجعة التسوية"
                : row.source === "legacy"
                  ? "نقل للمراجعة"
                  : row.status === "pending"
                    ? "اعتماد"
                    : "صرف"}
            </button>,
          );
      }
      if (tab === "payroll" && ["draft", "reviewed"].includes(row.status ?? "") && can("hr.payroll.prepare"))
        buttons.push(
          <button
            key="recalculate"
            className={hrSecondary}
            disabled={!online}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: "إعادة احتساب المسير",
                action: "payroll.recalculate",
                payload: { run_id: row.run_id, version: row.run_version },
                financial: true,
                fields: [{ name: "reason", label: "سبب إعادة الاحتساب", required: true }],
              });
            }}
          >
            إعادة احتساب
          </button>,
        );
      if (tab === "attendance" && row.attendanceId && can("hr.attendance.approve"))
        buttons.push(
          <button
            key="correct"
            className={hrSecondary}
            disabled={fetching}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: "تصحيح سجل الدوام",
                action: "attendance.correct",
                payload: { attendance_id: row.attendanceId, version: row.version },
                fields: [
                  {
                    name: "check_in",
                    label: "وقت الحضور",
                    type: "datetime-local",
                    required: true,
                    initial: hrLocalDateTime(row.check_in_at),
                  },
                  {
                    name: "check_out",
                    label: "وقت الانصراف",
                    type: "datetime-local",
                    initial: hrLocalDateTime(row.check_out_at),
                  },
                  { name: "reason", label: "سبب التصحيح", required: true },
                ],
              });
            }}
          >
            تصحيح
          </button>,
        );
      if (tab === "attendance" && row.attendanceId && (can("hr.attendance.record") || can("hr.self")))
        buttons.push(
          <button
            key="request-correction"
            className={hrSecondary}
            disabled={fetching}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: "طلب تصحيح حضور",
                action: "attendance.correction_request",
                payload: {
                  person_id: row.person_id,
                  attendance_id: row.attendanceId,
                  attendance_version: row.version,
                },
                fields: [
                  {
                    name: "check_in",
                    label: "وقت الحضور المطلوب",
                    type: "datetime-local",
                    initial: hrLocalDateTime(row.check_in_at),
                    required: true,
                  },
                  {
                    name: "check_out",
                    label: "وقت الانصراف المطلوب",
                    type: "datetime-local",
                    initial: hrLocalDateTime(row.check_out_at),
                  },
                  { name: "reason", label: "سبب طلب التصحيح", required: true },
                ],
              });
            }}
          >
            طلب تصحيح
          </button>,
        );
      if (tab === "payroll" && row.status === "draft" && can("hr.payroll.review"))
        buttons.push(
          <button
            key="review"
            className={hrSecondary}
            disabled={!online}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: "مراجعة المسير",
                action: "payroll.decide",
                payload: { run_id: row.run_id, version: row.run_version, status: "reviewed" },
                fields: [],
                financial: true,
              });
            }}
          >
            مراجعة
          </button>,
        );
      if (tab === "payroll" && row.status === "reviewed" && can("hr.payroll.approve"))
        buttons.push(
          <button
            key="approve"
            className={hrSecondary}
            disabled={!online}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: "اعتماد المسير وإثبات الاستحقاق",
                action: "payroll.decide",
                payload: { run_id: row.run_id, version: row.run_version, status: "approved" },
                fields: [],
                financial: true,
              });
            }}
          >
            اعتماد
          </button>,
        );
      const payout =
        (tab === "payroll" &&
          row.status === "approved" &&
          (row.remaining ?? 0) > 0 &&
          can("hr.payroll.pay")) ||
        (tab === "advances" && row.status === "approved" && can("hr.advance.pay"));
      if (payout)
        buttons.push(
          <button
            key="pay"
            className={hrSecondary}
            disabled={!online}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: tab === "payroll" ? "صرف راتب" : "صرف سلفة",
                action: tab === "payroll" ? "payroll.pay" : "advance.pay",
                financial: true,
                payload:
                  tab === "payroll" ? { item_id: row.id } : { advance_id: row.id, version: row.version },
                fields: [
                  {
                    name: "treasury_account_id",
                    label: "حساب الصرف",
                    numeric: true,
                    options: options(tools?.treasury_accounts ?? []),
                    required: true,
                  },
                  ...(tab === "payroll"
                    ? [
                        {
                          name: "amount",
                          label: "المبلغ (د.ع)",
                          type: "number" as const,
                          initial: String(row.remaining),
                          required: true,
                        },
                        { name: "reference", label: "مرجع الدفع" },
                      ]
                    : []),
                ],
              });
            }}
          >
            صرف
          </button>,
        );
      if (
        ((tab === "leave" && can("hr.leave.approve")) || (tab === "advances" && can("hr.advance.approve"))) &&
        row.status === "pending"
      )
        buttons.push(
          <button
            key="decide"
            className={hrSecondary}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: tab === "leave" ? "قرار الإجازة" : "قرار السلفة",
                action: tab === "leave" ? "leave.decide" : "advance.decide",
                financial: tab === "advances",
                payload: { [tab === "leave" ? "leave_id" : "advance_id"]: row.id, version: row.version },
                fields: [
                  {
                    name: "status",
                    label: "القرار",
                    options: [
                      { value: "approved", label: "موافقة" },
                      { value: "rejected", label: "رفض" },
                    ],
                    required: true,
                  },
                ],
              });
            }}
          >
            مراجعة الطلب
          </button>,
        );
      if (tab === "leave" && row.status === "approved" && can("hr.leave.approve"))
        buttons.push(
          <button
            key="cancel"
            className={hrSecondary}
            disabled={!online}
            onClick={(e) => {
              e.stopPropagation();
              setAction({
                title: "إلغاء إجازة معتمدة",
                action: "leave.cancel",
                financial: true,
                payload: { leave_id: row.id, version: row.version },
                fields: [{ name: "reason", label: "سبب الإلغاء", required: true }],
              });
            }}
          >
            إلغاء الإجازة
          </button>,
        );
      return (
        <div className="flex gap-2">
          {buttons.length ? (
            buttons
          ) : (
            <button
              className="text-xs text-violet"
              onClick={(e) => {
                e.stopPropagation();
                onOpen(row.person_id);
              }}
            >
              فتح الملف
            </button>
          )}
        </div>
      );
    },
  });
  return (
    <DataTable
      label={`سجلات ${tabs.find((t) => t.id === tab)?.label ?? "العمولات"}`}
      columns={columns}
      rows={display}
      loading={loading}
      fetching={fetching}
      error={error}
      onRetry={onRetry}
      emptyTitle="لا توجد سجلات لهذه الفترة"
      emptyHint="تظهر العمليات المحفوظة والمعتمدة هنا"
      onOpen={(r) => onOpen(r.person_id)}
    />
  );
}

function EmployeePanel({
  details,
  tools,
  can,
  onAction,
  onAttendance,
  onAdvance,
  onLeave,
}: {
  details: HRDetails;
  tools: HRLookups;
  can(permission: string): boolean;
  onAction(action: HRAction): void;
  onAttendance(event: "check_in" | "check_out"): void;
  onAdvance(): void;
  onLeave(): void;
}) {
  const [tab, setTab] = useState("overview");
  const [payslipOpen, setPayslipOpen] = useState(false);
  const [statementOpen, setStatementOpen] = useState(false);
  const [payslipMonth, setPayslipMonth] = useState(hrToday().slice(0, 7));
  const actorId = useSession((s) => s.session?.user.id);
  const row = details.person;
  const data = useQuery({
    queryKey: ["hr", "employee-tab", row.id, tab, payslipMonth],
    queryFn: () =>
      finora.hr.workspace(tab as Exclude<HRTab, "employees">, { person_id: row.id, month: payslipMonth }),
    enabled: !["overview", "profile"].includes(tab),
  });
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <header className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-xl font-bold">{row.name}</h2>
            <p className="mt-1 text-xs text-ink-soft">
              {row.job_title || "موظف"} · {row.department || "بدون قسم"}
            </p>
            <p className="mt-2 text-xs text-ink-faint">{row.code}</p>
          </div>
          <Avatar name={row.name} photo={row.photo_data} large />
        </div>
        <div className="flex items-center gap-3 text-xs">
          <HRBadge state={row.status} />
          <span className="text-ink-soft">{row.branch}</span>
          <span dir="ltr" className="ms-auto">
            {row.phone}
          </span>
        </div>
        {(["hr.payroll.view", "hr.commission.view", "hr.advance.view"].every(can) ||
          row.employee_id === actorId) && (
          <button className={hrSecondary} onClick={() => setStatementOpen(true)}>
            كشف الحساب المالي
          </button>
        )}
        {statementOpen && (
          <FinancialStatement
            personId={row.id}
            canExport={can("hr.reports.view") || (can("hr.self") && row.employee_id === actorId)}
            onClose={() => setStatementOpen(false)}
          />
        )}
      </header>
      <div
        className="flex flex-wrap gap-1 border-y border-line/60 bg-violet-soft/20 px-3 py-2"
        role="tablist"
        aria-label="ملف الموظف"
      >
        {[
          { id: "overview", label: "نظرة عامة" },
          { id: "attendance", label: "الدوام" },
          { id: "payroll", label: "الراتب", permission: "hr.payroll.view" },
          { id: "advances", label: "السلف", permission: "hr.advance.view" },
          { id: "leave", label: "الإجازات", permission: "hr.leave.manage" },
          { id: "profile", label: "الملف الوظيفي" },
        ].map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={cn(
              "rounded-control px-3 py-2 text-[11px]",
              tab === t.id ? "bg-violet-soft text-violet" : "text-ink-soft",
            )}
            onClick={() => setTab(t.id)}
            disabled={!!t.permission && !can(t.permission) && !can("hr.self")}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="space-y-4 p-4">
        {tab === "attendance" && <AttendanceCalendar personId={row.id} />}
        {tab === "leave" && (
          <section className="rounded-panel border border-line/70 p-4">
            <h3 className="text-xs font-semibold">رصيد الإجازات لهذا العام</h3>
            {details.leave_balances.map((balance) => (
              <div key={balance.id} className="mt-3 flex items-center justify-between gap-2 text-xs">
                <span>
                  {balance.name}
                  <small className="block text-ink-faint">
                    المستخدم: {balance.used} يوم · المتبقي: {balance.remaining ?? "بدون حد"}
                  </small>
                </span>
                {can("hr.settings.manage") && (
                  <button
                    className="text-violet"
                    onClick={() =>
                      onAction({
                        title: "تعديل استحقاق الإجازة",
                        action: "leave.entitlement",
                        payload: { person_id: row.id, version: row.version, type_id: balance.id },
                        fields: [
                          {
                            name: "yearly_half_days",
                            label: "الاستحقاق السنوي بوحدات نصف يوم (40 = 20 يوم)",
                            type: "number",
                            initial: String(2 * (balance.used + (balance.remaining ?? 0))),
                            required: true,
                          },
                        ],
                      })
                    }
                  >
                    تعديل
                  </button>
                )}
              </div>
            ))}
          </section>
        )}
        {tab === "payroll" && (
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="شهر قسيمة الراتب"
              type="month"
              className={`${hrInput} flex-1`}
              value={payslipMonth}
              onChange={(e) => setPayslipMonth(e.target.value)}
            />
            {(can("hr.reports.view") || (can("hr.self") && row.employee_id === actorId)) && (
              <button className={hrSecondary} onClick={() => setPayslipOpen(true)}>
                <Download size={16} />
                قسيمة الراتب
              </button>
            )}
          </div>
        )}
        {tab === "overview" || tab === "profile" ? (
          <>
            {row.salary !== undefined && (
              <div className="rounded-panel border border-violet/10 bg-violet-soft/30 p-4">
                <p className="text-xs text-ink-soft">
                  الأجر الأساسي · {labels[row.salary_type ?? "monthly"]}
                </p>
                <p className="mt-2 text-lg font-bold text-violet">{formatIqd(row.salary)}</p>
              </div>
            )}
            <section className="rounded-panel border border-line/70">
              <h3 className="bg-violet-soft/30 px-4 py-3 text-xs font-semibold">معلومات الموظف</h3>
              {[
                ["الرقم الوظيفي", row.code],
                ["القسم", row.department],
                ["تاريخ التعيين", row.joined_on],
                ["نوع العقد", labels[row.contract_type] ?? row.contract_type],
                ["الفرع", row.branch],
                ["البريد الإلكتروني", row.email],
                ["الملاحظات", row.notes],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex justify-between gap-3 border-t border-line/50 px-4 py-3 text-xs"
                >
                  <span className="text-ink-faint">{label}</span>
                  <span>{value || "—"}</span>
                </div>
              ))}
            </section>
            {tab === "overview" && (
              <section className="rounded-panel border border-line/70 p-4">
                <h3 className="text-xs font-semibold">حالة الدوام اليوم</h3>
                <div className="mt-3 flex justify-between">
                  {details.attendance ? <HRBadge state={details.attendance.state} /> : <span>—</span>}
                  <span className="text-xs text-ink-soft">
                    {details.attendance?.check_in || "—"} · {hours(details.attendance?.worked_minutes ?? 0)}
                  </span>
                </div>
              </section>
            )}
            {tab === "profile" && can("hr.shifts.manage") && (
              <button
                className={`${hrSecondary} w-full`}
                onClick={() =>
                  onAction({
                    title: "تعيين وردية",
                    action: "shift.assign",
                    payload: { person_id: row.id, version: row.version },
                    fields: [
                      {
                        name: "shift_id",
                        label: "الوردية",
                        numeric: true,
                        options: options(tools.shifts.filter((s) => s.branch_id === row.branch_id)),
                        required: true,
                      },
                      {
                        name: "effective_from",
                        label: "تاريخ السريان",
                        type: "date",
                        initial: hrToday(),
                        required: true,
                      },
                    ],
                  })
                }
              >
                تعيين وردية
              </button>
            )}
            {tab === "profile" && can("hr.resources.manage") && (
              <button
                className={`${hrSecondary} w-full`}
                onClick={() =>
                  onAction({
                    title: "إضافة سجل وظيفي",
                    action: "resource.record",
                    payload: { person_id: row.id },
                    fields: [
                      {
                        name: "kind",
                        label: "نوع السجل",
                        options: ["review", "goal", "warning", "note"].map((v) => ({
                          value: v,
                          label: labels[v] ?? v,
                        })),
                        required: true,
                      },
                      { name: "title", label: "العنوان", required: true },
                      { name: "period", label: "فترة التقييم" },
                      { name: "score", label: "النتيجة من 100 (للتقييم)", type: "number", initial: "0" },
                      { name: "note", label: "التفاصيل", type: "textarea" },
                    ],
                  })
                }
              >
                تقييم أو إجراء إداري
              </button>
            )}
            {tab === "profile" && (
              <PersonnelResources details={details} tools={tools} can={can} onAction={onAction} />
            )}
            {tab === "profile" && (can("hr.commission.view") || can("hr.commission.manage")) && (
              <CommissionSettings details={details} can={can} onAction={onAction} />
            )}
            {details.contracts.length > 0 && tab === "profile" && (
              <section className="rounded-panel border border-line/70 p-4">
                <h3 className="text-xs font-semibold">نسخ العقد المالي</h3>
                {details.contracts.map((c) => (
                  <p key={c.id} className="mt-3 flex justify-between text-xs">
                    <span>{c.effective_from}</span>
                    <span>
                      {formatIqd(c.salary)} · {labels[c.salary_type]}
                    </span>
                  </p>
                ))}
              </section>
            )}
            {tab === "overview" && (
              <>
                <h3 className="text-xs font-semibold">إجراءات سريعة</h3>
                <div className="grid grid-cols-2 gap-2">
                  {(can("hr.attendance.record") || can("hr.self")) && (
                    <button
                      className={hrSecondary}
                      onClick={() =>
                        onAttendance(
                          details.attendance?.check_in && !details.attendance.check_out
                            ? "check_out"
                            : "check_in",
                        )
                      }
                    >
                      <Fingerprint size={16} />
                      {details.attendance?.check_in && !details.attendance.check_out
                        ? "تسجيل انصراف"
                        : "تسجيل حضور"}
                    </button>
                  )}
                  {can("hr.advance.create") && (
                    <button className={hrSecondary} onClick={onAdvance}>
                      طلب سلفة
                    </button>
                  )}
                  {(can("hr.leave.manage") || can("hr.self")) && (
                    <button className={hrSecondary} onClick={onLeave}>
                      <CalendarDays size={16} />
                      طلب إجازة
                    </button>
                  )}
                </div>
              </>
            )}
            {details.history.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold">آخر العمليات</h3>
                {details.history.slice(0, 6).map((h) => (
                  <div key={h.id} className="mt-3 flex justify-between text-[11px] text-ink-soft">
                    <span>
                      {h.action
                        .split(".")
                        .map((x) => labels[x] ?? x)
                        .join(" · ")}
                    </span>
                    <time>{new Date(h.date).toLocaleDateString("ar-IQ")}</time>
                  </div>
                ))}
              </section>
            )}
          </>
        ) : data.isLoading ? (
          <Loader2 className="mx-auto animate-spin text-violet" />
        ) : data.error ? (
          <p role="alert" className="text-sm text-danger">
            {toFinoraError(data.error).message}
          </p>
        ) : data.data?.rows.length ? (
          <div className="space-y-3">
            {data.data.rows.map((r, i) => (
              <div key={r.id ?? i} className="rounded-control border border-line p-3 text-xs">
                <div className="flex justify-between">
                  <span>{r.date || r.starts || r.first_month || "سجل"}</span>
                  <HRBadge state={r.state ?? r.status ?? "pending"} />
                </div>
                {r.net !== undefined && (
                  <p className="mt-2">
                    الصافي {formatIqd(r.net)} · المتبقي {formatIqd(r.remaining ?? 0)}
                  </p>
                )}
                {r.amount !== undefined && (
                  <p className="mt-2">
                    المبلغ {formatIqd(r.amount)} · المتبقي {formatIqd(r.remaining ?? 0)}
                  </p>
                )}
                {r.check_in && (
                  <p className="mt-2">
                    الحضور {r.check_in} · الانصراف {r.check_out || "—"}
                  </p>
                )}
                {r.type && (
                  <p className="mt-2">
                    {r.type} · {r.starts} — {r.ends}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-ink-faint">لا توجد سجلات</p>
        )}
      </div>
      {payslipOpen && (
        <HRReportDialog
          tab="payroll"
          query={{ period: "custom", person_id: row.id, month: payslipMonth }}
          onClose={() => setPayslipOpen(false)}
        />
      )}
    </div>
  );
}
