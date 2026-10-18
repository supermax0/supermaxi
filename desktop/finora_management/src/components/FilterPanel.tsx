import { ChevronDown, Filter } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { cn } from "@/utils/cn";
import { Popover } from "./Popover";

interface FilterPanelProps {
  activeCount: number;
  onApply(): void;
  onClear(): void;
  children: ReactNode;
}

/** "تصفية" button with a floating panel of fields; shows how many filters are active. */
export function FilterPanel({ activeCount, onApply, onClear, children }: FilterPanelProps) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  return (
    <div className="relative">
      <button
        ref={anchor}
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "flex h-11 items-center gap-2 rounded-control border bg-white/85 px-4 text-sm shadow-control transition-colors",
          activeCount > 0
            ? "border-violet/40 text-violet-deep"
            : "border-line text-ink hover:border-violet/30",
        )}
      >
        <Filter size={16} aria-hidden />
        تصفية
        {activeCount > 0 && (
          <span className="ltr-isolate grid h-5 min-w-5 place-items-center rounded-full bg-violet px-1 text-[11px] font-semibold text-white">
            {activeCount}
          </span>
        )}
        <ChevronDown size={15} className={cn("transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={anchor}
        label="تصفية"
        align="start"
        width={380}
        className="p-4"
      >
        <div className="grid grid-cols-2 gap-3">{children}</div>
        <div className="mt-4 flex justify-between gap-2 border-t border-line pt-3">
          <button
            type="button"
            onClick={() => {
              onClear();
              setOpen(false);
            }}
            className="h-9 rounded-control px-3 text-sm text-ink-soft hover:bg-surface-sunken"
          >
            مسح التصفية
          </button>
          <button
            type="button"
            onClick={() => {
              onApply();
              setOpen(false);
            }}
            className="h-9 rounded-control bg-gradient-to-l from-violet to-violet-deep px-5 text-sm font-semibold text-white shadow-control"
          >
            تطبيق
          </button>
        </div>
      </Popover>
    </div>
  );
}

const fieldClass =
  "h-10 w-full rounded-[11px] border border-line bg-white px-3 text-sm text-ink outline-none focus:border-violet/50 focus:ring-4 focus:ring-violet/10";

interface FieldProps {
  label: string;
  wide?: boolean;
  children: ReactNode;
}

export function Field({ label, wide, children }: FieldProps) {
  return (
    <label
      className={cn("flex flex-col gap-1.5 text-[12.5px] font-medium text-ink-soft", wide && "col-span-2")}
    >
      {label}
      {children}
    </label>
  );
}

export function SelectInput({
  value,
  onChange,
  options,
  placeholder,
}: {
  value: string;
  onChange(value: string): void;
  options: Array<{ value: string; label: string }>;
  placeholder: string;
}) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)} className={fieldClass}>
      <option value="">{placeholder}</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function DateInput({ value, onChange }: { value: string; onChange(value: string): void }) {
  return (
    <input
      type="date"
      dir="ltr"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={fieldClass}
    />
  );
}

export function NumberInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange(value: string): void;
  placeholder?: string;
}) {
  return (
    <input
      inputMode="numeric"
      dir="ltr"
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ""))}
      className={fieldClass}
    />
  );
}
