import { Loader2, ScanBarcode, Search, X } from "lucide-react";
import { forwardRef, type KeyboardEvent } from "react";
import { cn } from "@/utils/cn";

interface SearchBoxProps {
  value: string;
  onChange(value: string): void;
  placeholder: string;
  /** Called on Enter (e.g. to search immediately without waiting for the debounce). */
  onSubmit?(value: string): void;
  busy?: boolean;
  scanner?: boolean;
  className?: string;
}

export const SearchBox = forwardRef<HTMLInputElement, SearchBoxProps>(function SearchBox(
  { value, onChange, placeholder, onSubmit, busy = false, scanner = false, className },
  ref,
) {
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") onSubmit?.(value);
    if (event.key === "Escape" && value) {
      event.stopPropagation();
      onChange("");
    }
  };
  return (
    <label
      className={cn(
        "flex h-11 items-center gap-2.5 rounded-control border border-line bg-white/85 px-3.5 shadow-control",
        "focus-within:border-violet/45 focus-within:ring-4 focus-within:ring-violet/10",
        className,
      )}
    >
      {busy ? (
        <Loader2 size={17} className="animate-spin text-violet" aria-hidden />
      ) : (
        <Search size={17} className="text-ink-faint" aria-hidden />
      )}
      <input
        ref={ref}
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label={placeholder}
        className="h-full min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint [&::-webkit-search-cancel-button]:hidden"
      />
      {value ? (
        <button
          type="button"
          aria-label="مسح البحث"
          onClick={() => onChange("")}
          className="text-ink-faint hover:text-ink"
        >
          <X size={15} />
        </button>
      ) : (
        scanner && <ScanBarcode size={17} className="text-ink-faint" aria-label="يدعم قارئ الباركود" />
      )}
    </label>
  );
});
