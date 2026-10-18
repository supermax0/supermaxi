import { motion } from "framer-motion";
import { useId } from "react";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  count?: number;
}

interface StatusTabsProps<T extends string> {
  tabs: TabItem<T>[];
  value: T;
  onChange(value: T): void;
  label: string;
}

/** Segmented status tabs with live counts; the active pill slides between tabs. */
export function StatusTabs<T extends string>({ tabs, value, onChange, label }: StatusTabsProps<T>) {
  const pillId = useId();
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex items-center gap-1 rounded-control bg-white/70 p-1 shadow-control"
    >
      {tabs.map((tab) => {
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={cn(
              "relative flex h-9 items-center gap-2 rounded-[11px] px-4 text-[13.5px] font-medium transition-colors duration-150",
              active ? "text-violet-deep" : "text-ink-soft hover:text-ink",
            )}
          >
            {active && (
              <motion.span
                layoutId={`tab-pill-${pillId}`}
                className="absolute inset-0 rounded-[11px] bg-violet-soft ring-1 ring-violet/15"
                transition={{ type: "spring", stiffness: 520, damping: 42 }}
              />
            )}
            <span className="relative">{tab.label}</span>
            {tab.count !== undefined && (
              <span
                className={cn(
                  "ltr-isolate relative rounded-full px-1.5 text-[11.5px]",
                  active ? "bg-white/80 text-violet-deep" : "bg-surface-sunken text-ink-faint",
                )}
              >
                {formatNumber(tab.count)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
