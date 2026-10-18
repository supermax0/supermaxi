import { Check, Minus } from "lucide-react";
import { cn } from "@/utils/cn";

interface CheckboxProps {
  checked: boolean;
  indeterminate?: boolean;
  label: string;
  onChange(checked: boolean): void;
}

export function Checkbox({ checked, indeterminate = false, label, onChange }: CheckboxProps) {
  const on = checked || indeterminate;
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? "mixed" : checked}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onChange(!checked);
      }}
      className={cn(
        "grid h-[18px] w-[18px] place-items-center rounded-[6px] border transition-colors duration-150",
        on ? "border-violet bg-violet text-white" : "border-ink-faint/50 bg-white hover:border-violet/60",
      )}
    >
      {indeterminate ? (
        <Minus size={12} strokeWidth={3} />
      ) : checked ? (
        <Check size={12} strokeWidth={3} />
      ) : null}
    </button>
  );
}
