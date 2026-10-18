import { AlertTriangle, CheckCircle2, Clock3, RotateCcw, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import type { ManifestSummary, RowStatus } from "@/api/finora/shipping";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";

export type Section = "overview" | "carriers" | "agents" | "manifests" | "settlements" | "returns";

export const SECTIONS: Array<{ id: Section; label: string }> = [
  { id: "overview", label: "نظرة عامة" },
  { id: "carriers", label: "شركات النقل" },
  { id: "agents", label: "المندوبون" },
  { id: "manifests", label: "الكشوف" },
  { id: "settlements", label: "التسويات المالية" },
  { id: "returns", label: "المرتجعات" },
];

export const STATUS_STYLE: Record<
  RowStatus,
  { label: string; key: string; tone: string; dot: string; icon: LucideIcon }
> = {
  واصل: {
    label: "واصل",
    key: "F2",
    tone: "bg-success-soft text-success",
    dot: "bg-success",
    icon: CheckCircle2,
  },
  راجع: { label: "راجع", key: "F3", tone: "bg-danger-soft text-danger", dot: "bg-danger", icon: RotateCcw },
  مؤجل: { label: "مؤجل", key: "F4", tone: "bg-warning-soft text-warning", dot: "bg-warning", icon: Clock3 },
  مشكلة: {
    label: "مشكلة",
    key: "",
    tone: "bg-surface-sunken text-ink-soft",
    dot: "bg-ink-faint",
    icon: AlertTriangle,
  },
};

/** FINORA manifests also carry the portal / executor spellings (ملغي، Delivered…) — map them onto the four classes. */
const STATUS_ALIASES: Record<string, RowStatus> = {
  واصل: "واصل",
  Delivered: "واصل",
  استبدال: "واصل",
  Replacement: "واصل",
  "تم التوصيل": "واصل",
  راجع: "راجع",
  ملغي: "راجع",
  Canceled: "راجع",
  مؤجل: "مؤجل",
  Delayed: "مؤجل",
  مشكلة: "مشكلة",
};

export function normalizeStatus(value: string | null | undefined): RowStatus | "" {
  return (value && STATUS_ALIASES[value.trim()]) || "";
}

export const KIND_LABEL: Record<ManifestSummary["kind"], string> = {
  settlement: "تسوية",
  handover: "تسليم",
  agent: "مندوب",
};

export function money(value: number): string {
  return `${formatNumber(value)} د.ع`;
}

export function Money({ value, className }: { value: number; className?: string }) {
  return (
    <span className={cn("ltr-isolate whitespace-nowrap", className)}>
      {formatNumber(value)} <span className="text-[0.8em] font-medium text-ink-faint">د.ع</span>
    </span>
  );
}

export function ManifestState({ executed, partial = false }: { executed: boolean; partial?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold",
        !executed
          ? "bg-violet-soft text-violet-deep"
          : partial
            ? "bg-warning-soft text-warning"
            : "bg-success-soft text-success",
      )}
    >
      {executed ? <CheckCircle2 size={12} /> : <Clock3 size={12} />}
      {!executed ? "مسودة" : partial ? "مسوى جزئياً" : "معتمد"}
    </span>
  );
}

export function Panel({
  title,
  icon: Icon,
  actions,
  children,
  className,
}: {
  title: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("glass flex min-h-0 flex-col rounded-panel p-4", className)}>
      <header className="mb-3 flex items-center gap-2">
        {Icon && (
          <span className="grid h-8 w-8 place-items-center rounded-control bg-maroon-soft text-maroon">
            <Icon size={16} />
          </span>
        )}
        <h3 className="flex-1 text-sm font-bold text-ink">{title}</h3>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function Metric({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-control bg-surface-sunken/60 px-3 py-2.5">
      <p className="text-[11px] text-ink-faint">{label}</p>
      <p className={cn("mt-0.5 text-[15px] font-bold text-ink", tone)}>{value}</p>
    </div>
  );
}

/** Splits pasted / scanned text into order numbers or waybills (lines, commas, tabs, spaces). */
export function splitCodes(text: string): string[] {
  return text
    .split(/[\s,;،\t]+/)
    .map((c) => c.trim().replace(/^#/, ""))
    .filter(Boolean);
}

/** First-column codes from a CSV / spreadsheet export (header row skipped when it is not a number). */
export function codesFromCsv(text: string): string[] {
  const lines = text
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter((l) => l.trim());
  const codes: string[] = [];
  for (const [index, line] of lines.entries()) {
    const first = (line.split(/[,;\t]/)[0] ?? "").replace(/^"|"$/g, "").trim();
    if (!first) continue;
    if (index === 0 && !/\d/.test(first)) continue;
    codes.push(first.replace(/^#/, ""));
  }
  return codes;
}
