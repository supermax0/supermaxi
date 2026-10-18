import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-panel border border-dashed border-line bg-surface-sunken/60 px-8 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-panel bg-white text-violet shadow-control">
        <Icon size={26} strokeWidth={1.7} aria-hidden />
      </span>
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <p className="max-w-md text-sm leading-6 text-ink-soft">{description}</p>
      {action}
    </div>
  );
}
