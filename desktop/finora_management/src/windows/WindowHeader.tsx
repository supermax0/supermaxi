import { Maximize2, Minimize2, Minus, X } from "lucide-react";
import type { ReactNode } from "react";
import { IconButton } from "@/components/IconButton";
import { useWindowManager } from "@/stores/windowManager";
import type { WindowDefinition } from "./registry";

interface WindowHeaderProps {
  definition: WindowDefinition;
  /** Window-specific tools rendered between the title and the window controls. */
  actions?: ReactNode;
}

export function WindowHeader({ definition, actions }: WindowHeaderProps) {
  const expanded = useWindowManager((s) => s.expanded);
  const toggleExpanded = useWindowManager((s) => s.toggleExpanded);
  const minimize = useWindowManager((s) => s.minimize);
  const close = useWindowManager((s) => s.close);
  const Icon = definition.icon;

  return (
    <header
      className={
        definition.compactHeader
          ? "flex items-center gap-4 px-6 pb-2.5 pt-3.5"
          : "flex items-center gap-4 px-7 pb-4 pt-6"
      }
    >
      <div className="flex items-center gap-3.5">
        <span className="grid h-12 w-12 place-items-center rounded-control bg-white shadow-control">
          <Icon className={definition.accent} size={24} strokeWidth={1.8} aria-hidden />
        </span>
        <div>
          <h1 className="text-[22px] font-bold leading-tight text-ink">{definition.title}</h1>
          {!definition.compactHeader && (
            <p className="mt-0.5 text-[13px] text-ink-faint">{definition.subtitle}</p>
          )}
        </div>
      </div>
      <div className="ms-auto flex items-center gap-2">{actions}</div>
      <div className="flex items-center gap-0.5" role="group" aria-label="التحكم بالنافذة">
        <IconButton label="تصغير إلى الشريط العلوي" size="sm" onClick={minimize}>
          <Minus size={16} />
        </IconButton>
        <IconButton label={expanded ? "استعادة الحجم" : "توسيع النافذة"} size="sm" onClick={toggleExpanded}>
          {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </IconButton>
        <IconButton label="إغلاق النافذة" size="sm" onClick={close}>
          <X size={17} />
        </IconButton>
      </div>
    </header>
  );
}
