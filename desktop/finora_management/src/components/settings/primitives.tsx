import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/utils/cn";

export function SettingRow({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-6 border-b border-line/60 py-3.5 last:border-0">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        {hint && <p className="mt-0.5 text-xs leading-5 text-ink-faint">{hint}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export function Switch({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange(v: boolean): void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "h-6 w-11 rounded-full p-0.5 transition-colors disabled:opacity-40",
        checked ? "bg-violet" : "bg-line",
      )}
    >
      <span
        className={cn(
          "block h-5 w-5 rounded-full bg-white shadow transition-transform duration-200",
          checked ? "-translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}

export function SectionCard({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <section className="rounded-panel bg-white/80 px-5 py-2 ring-1 ring-line/60">
      <h3 className="flex items-center gap-2 border-b border-line/60 py-3 text-[13px] font-semibold text-ink-soft">
        <Icon size={16} aria-hidden />
        {title}
      </h3>
      {children}
    </section>
  );
}
