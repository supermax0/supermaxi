import { cn } from "@/utils/cn";

export type Tone = "azure" | "violet" | "warning" | "success" | "danger" | "neutral";

export const TONE_CLASSES: Record<Tone, string> = {
  azure: "bg-azure-soft text-azure",
  violet: "bg-violet-soft text-violet-deep",
  warning: "bg-warning-soft text-warning",
  success: "bg-success-soft text-success",
  danger: "bg-danger-soft text-danger",
  neutral: "bg-surface-sunken text-ink-soft",
};

export function StatusBadge({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 min-w-[78px] items-center justify-center whitespace-nowrap rounded-full px-3 text-[12.5px] font-medium",
        TONE_CLASSES[tone],
      )}
    >
      {label}
    </span>
  );
}
