import { useState } from "react";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { selectAfterFormatSwap } from "@/utils/selectOnFocus";

/** Whole-dinar input: raw digits while focused, 1,250,000 otherwise. */
export function MoneyInput({
  value,
  onChange,
  label,
  className,
  placeholder = "0",
}: {
  value: number;
  onChange(value: number): void;
  label: string;
  className?: string;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <input
      aria-label={label}
      dir="ltr"
      inputMode="numeric"
      placeholder={placeholder}
      value={draft ?? (value ? formatNumber(value) : "")}
      onFocus={(event) => {
        const raw = value ? String(value) : "";
        setDraft(raw);
        selectAfterFormatSwap(event.target, raw);
      }}
      onChange={(event) => {
        const digits = event.target.value.replace(/\D/g, "");
        setDraft(digits);
        onChange(Number(digits) || 0);
      }}
      onBlur={() => setDraft(null)}
      className={cn(
        "ltr-isolate h-9 rounded-[10px] border border-line bg-white px-2.5 text-center text-sm outline-none transition-colors focus:border-violet/45",
        className,
      )}
    />
  );
}
