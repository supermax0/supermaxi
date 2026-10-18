import type { LucideIcon } from "lucide-react";
import { cn } from "@/utils/cn";
import { TONE_CLASSES, type Tone } from "./StatusBadge";

interface StatCardProps {
  label: string;
  value: string;
  unit?: string;
  icon: LucideIcon;
  tone: Tone;
  loading?: boolean;
  active?: boolean;
  onClick?(): void;
}

const GLOW: Record<Tone, string> = {
  azure: "from-azure-soft/80",
  violet: "from-violet-soft/90",
  warning: "from-warning-soft/90",
  success: "from-success-soft/80",
  danger: "from-danger-soft/90",
  neutral: "from-surface-sunken",
};

export function StatCard({ label, value, unit, icon: Icon, tone, loading, active, onClick }: StatCardProps) {
  const Element = onClick ? "button" : "div";
  return (
    <Element
      type={onClick ? "button" : undefined}
      onClick={onClick}
      aria-pressed={onClick ? Boolean(active) : undefined}
      className={cn(
        "flex min-w-0 flex-1 items-center gap-4 rounded-panel bg-gradient-to-l to-white/90 px-5 py-4 text-start shadow-control ring-1 transition-[box-shadow,transform] duration-200",
        GLOW[tone],
        active ? "ring-2 ring-violet/40" : "ring-white/80",
        onClick && "hover:-translate-y-0.5 hover:shadow-glass",
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13.5px] font-medium text-ink-soft">{label}</p>
        {loading ? (
          <span className="mt-2 block h-6 w-20 animate-pulse rounded-full bg-line" />
        ) : (
          <p className="mt-1 flex items-baseline gap-1.5">
            <span className="ltr-isolate text-[24px] font-bold leading-tight text-ink">{value}</span>
            {unit && <span className="text-xs text-ink-faint">{unit}</span>}
          </p>
        )}
      </div>
      <span className={cn("grid h-12 w-12 shrink-0 place-items-center rounded-control", TONE_CLASSES[tone])}>
        <Icon size={22} strokeWidth={1.8} aria-hidden />
      </span>
    </Element>
  );
}
