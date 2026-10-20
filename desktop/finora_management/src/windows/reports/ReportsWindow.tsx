import { useMutation, useQuery } from "@tanstack/react-query";
import { CalendarDays, FileSpreadsheet, FileText, Layers, Printer, UserRound, Warehouse } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";
import { useWorkspaceHistory, useWorkspaceRequest } from "@/features/workspace/navigation";
import { finora, toFinoraError } from "@/api/finora";
import {
  REPORT_PERIODS,
  REPORT_SECTIONS,
  type ReportFilters,
  type ReportPeriod,
  type ReportSection,
  type SectionOptions,
} from "@/api/finora/reports";
import { Menu, type MenuItem } from "@/components/Menu";
import { SelectMenu } from "@/components/SelectMenu";
import { defaultFilters, PERIOD_LABELS, SECTION_INFO } from "@/features/reports/labels";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { ReportsDashboard } from "./ReportsDashboard";
import { SectionReport } from "./SectionReport";

type ExportFormat = "print" | "pdf" | "xlsx";

const dateBox =
  "flex h-10 items-center gap-1.5 rounded-control border border-line bg-white px-2 text-sm text-ink shadow-control focus-within:border-violet/45";

/**
 * Reports: one dashboard + ten detail reports. The filters live here so a
 * drill-down ("فتح التفاصيل") opens the detail report on the same period,
 * branch and employee without choosing them again.
 */
export function ReportsWindow() {
  const active = useWindowManager((s) => s.active === "reports");
  const online = useConnection((s) => s.status === "online");
  const [filters, setFilters] = useState<ReportFilters>(() => defaultFilters());
  const [view, setView] = useState<ReportSection | "dashboard">("dashboard");
  const [viewOptions, setViewOptions] = useState<SectionOptions>({});
  useWorkspaceRequest("reports", (target) => {
    if (target.period)
      setFilters({
        ...defaultFilters(),
        period: target.period,
        ...(target.dateFrom ? { dateFrom: target.dateFrom } : {}),
        ...(target.dateTo ? { dateTo: target.dateTo } : {}),
      });
    if (target.tab && REPORT_SECTIONS.includes(target.tab as ReportSection)) {
      setView(target.tab as ReportSection);
      setViewOptions({});
    } else if (target.tab === "dashboard") setView("dashboard");
  });
  useWorkspaceHistory({
    window: "reports",
    tab: view,
    period: filters.period,
    dateFrom: filters.dateFrom,
    dateTo: filters.dateTo,
  });
  const meta = useQuery({
    queryKey: ["reports", "meta"],
    queryFn: () => finora.reports.meta(),
    enabled: active,
    staleTime: 5 * 60_000,
  });
  const allowed = (section: ReportSection) => meta.data?.sections[section] ?? false;

  const update = (patch: Partial<ReportFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const open = useCallback((section: ReportSection) => {
    setViewOptions({});
    setView(section);
  }, []);

  const exporter = useMutation({
    mutationFn: ({ section, format }: { section: ReportSection; format: ExportFormat }) =>
      finora.reports.export(
        section,
        format,
        SECTION_INFO[section].title,
        filters,
        section === view ? viewOptions : {},
      ),
    onSuccess: (result, { format }) => {
      if (format !== "print" && result.saved)
        toast.success(`تم حفظ الملف${result.path ? `: ${result.path}` : ""}`);
    },
    onError: (error) =>
      toast.error(
        error instanceof Error && !("kind" in error) ? error.message : toFinoraError(error).message,
      ),
  });

  const exportable = REPORT_SECTIONS.filter(allowed);
  const exportButton = (format: ExportFormat, label: string, icon: ReactNode, className: string) => {
    const disabled = !online || exporter.isPending || !meta.data?.can_export;
    const button = (props: Record<string, unknown> = {}) => (
      <button
        {...props}
        type="button"
        disabled={disabled}
        className={cn(
          "flex h-10 items-center gap-2 rounded-control px-4 text-sm font-semibold transition-colors disabled:opacity-45",
          className,
        )}
      >
        {icon}
        {label}
      </button>
    );
    if (view !== "dashboard")
      return button({
        onClick: () => exporter.mutate({ section: view, format }),
        "aria-label": `${label} — ${SECTION_INFO[view].title}`,
      });
    const items: MenuItem[] = exportable.map((section) => ({
      id: section,
      label: SECTION_INFO[section].title,
      icon: SECTION_INFO[section].icon,
      onSelect: () => exporter.mutate({ section, format }),
    }));
    return (
      <Menu label={label} items={items} trigger={(props) => button({ ...props, "aria-label": label })} />
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <SelectMenu
          icon={CalendarDays}
          label="الفترة الزمنية"
          value={filters.period}
          onChange={(value) => update({ period: value as ReportPeriod })}
          className="w-[150px]"
          menuWidth={200}
          options={REPORT_PERIODS.map((p) => ({ value: p, label: PERIOD_LABELS[p] }))}
        />
        {filters.period === "custom" && (
          <div className={dateBox}>
            <input
              type="date"
              aria-label="من تاريخ"
              value={filters.dateFrom}
              max={filters.dateTo}
              onChange={(e) => e.target.value && update({ dateFrom: e.target.value })}
              className="ltr-isolate h-full bg-transparent text-sm outline-none"
            />
            <span className="text-ink-faint">—</span>
            <input
              type="date"
              aria-label="إلى تاريخ"
              value={filters.dateTo}
              min={filters.dateFrom}
              onChange={(e) => e.target.value && update({ dateTo: e.target.value })}
              className="ltr-isolate h-full bg-transparent text-sm outline-none"
            />
          </div>
        )}
        {meta.data?.can_pick_branch && (
          <SelectMenu
            icon={Warehouse}
            label="الفرع"
            value={String(filters.branchId ?? "")}
            onChange={(value) => update({ branchId: Number(value) || null })}
            className="w-[160px]"
            options={[
              { value: "", label: "كل الفروع" },
              ...meta.data.branches.map((b) => ({ value: String(b.id), label: b.name })),
            ]}
          />
        )}
        <SelectMenu
          icon={UserRound}
          label="الموظف"
          value={String(filters.employeeId ?? "")}
          onChange={(value) => update({ employeeId: Number(value) || null })}
          className="w-[170px]"
          menuWidth={280}
          searchable
          options={[
            { value: "", label: "كل الموظفين" },
            ...(meta.data?.employees ?? []).map((e) => ({ value: String(e.id), label: e.name })),
          ]}
        />
        <SelectMenu
          icon={Layers}
          label="نوع التقرير"
          value={view}
          onChange={(value) => (value === "dashboard" ? setView("dashboard") : open(value as ReportSection))}
          className="w-[190px]"
          menuWidth={240}
          searchable={false}
          options={[
            { value: "dashboard", label: "كل أنواع التقارير", icon: Layers },
            ...REPORT_SECTIONS.filter(allowed).map((section) => ({
              value: section,
              label: SECTION_INFO[section].title,
              icon: SECTION_INFO[section].icon,
            })),
          ]}
        />
        <div className="ms-auto flex items-center gap-2">
          {exportButton(
            "pdf",
            "PDF",
            <FileText size={16} aria-hidden />,
            "bg-danger-soft text-danger hover:bg-danger hover:text-white",
          )}
          {exportButton(
            "xlsx",
            "Excel",
            <FileSpreadsheet size={16} aria-hidden />,
            "bg-success-soft text-success hover:bg-success hover:text-white",
          )}
          {exportButton(
            "print",
            "طباعة",
            <Printer size={16} aria-hidden />,
            "bg-violet text-white hover:bg-violet-deep",
          )}
        </div>
      </div>

      {meta.error ? (
        <p role="alert" className="rounded-control bg-danger-soft px-4 py-3 text-sm text-danger">
          {toFinoraError(meta.error).kind === "not_found"
            ? "خادم FINORA المتصل لم يُحدَّث بعد لدعم التقارير الجديدة."
            : toFinoraError(meta.error).message}
        </p>
      ) : view === "dashboard" ? (
        <ReportsDashboard filters={filters} active={active} onOpen={open} />
      ) : (
        <SectionReport
          key={view}
          section={view}
          filters={filters}
          active={active}
          onBack={() => setView("dashboard")}
          onOptions={setViewOptions}
        />
      )}
    </div>
  );
}
