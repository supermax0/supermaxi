import { Check, ChevronDown, Search, type LucideIcon } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/utils/cn";
import { Popover } from "./Popover";

export interface SelectOption {
  value: string;
  label: string;
  /** Small secondary text under the label. */
  hint?: string;
  icon?: LucideIcon;
}

interface SelectMenuProps {
  label: string;
  value: string;
  options: SelectOption[];
  onChange(value: string): void;
  icon?: LucideIcon;
  /** Show a search box (defaults to on when there are more than 8 options). */
  searchable?: boolean;
  className?: string;
  menuWidth?: number;
}

/** Arabic-friendly match: ignores case, diacritics and alef/yeh/teh-marbuta variants. */
function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[ً-ٰٟ]/g, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .trim();
}

/**
 * Styled dropdown replacing the native <select>: glass panel, check mark on
 * the chosen item, search for long lists, full keyboard support
 * (↑ ↓ Home End Enter Esc, type to search).
 */
export function SelectMenu({
  label,
  value,
  options,
  onChange,
  icon: Icon,
  searchable,
  className,
  menuWidth = 260,
}: SelectMenuProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const anchor = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const listId = useId();
  const withSearch = searchable ?? options.length > 8;
  const selected = options.find((o) => o.value === value);

  const filtered = useMemo(() => {
    const q = normalize(query);
    return q ? options.filter((o) => normalize(`${o.label} ${o.hint ?? ""}`).includes(q)) : options;
  }, [options, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    const index = Math.max(
      0,
      options.findIndex((o) => o.value === value),
    );
    setCursor(index);
    requestAnimationFrame(() => {
      if (withSearch) search.current?.focus();
      else list.current?.focus();
      list.current
        ?.querySelector<HTMLElement>(`[data-index="${index}"]`)
        ?.scrollIntoView?.({ block: "nearest" });
    });
  }, [open, options, value, withSearch]);

  useEffect(() => {
    list.current
      ?.querySelector<HTMLElement>(`[data-index="${cursor}"]`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [cursor]);

  const choose = (option: SelectOption | undefined) => {
    if (!option) return;
    onChange(option.value);
    setOpen(false);
    anchor.current?.focus();
  };

  const onKey = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(filtered.length - 1, c + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (event.key === "Home") {
      event.preventDefault();
      setCursor(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setCursor(filtered.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(filtered[cursor]);
    }
  };

  return (
    <>
      <button
        ref={anchor}
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className={cn(
          "flex h-10 min-w-0 items-center gap-2 rounded-control border bg-white px-3 text-sm text-ink shadow-control transition-[border-color,box-shadow]",
          open ? "border-violet/50 ring-4 ring-violet/10" : "border-line hover:border-violet/30",
          className,
        )}
      >
        {Icon && <Icon size={16} className="shrink-0 text-violet" aria-hidden />}
        <span className="min-w-0 flex-1 truncate text-start">{selected?.label ?? label}</span>
        <ChevronDown
          size={15}
          className={cn("shrink-0 text-ink-faint transition-transform duration-200", open && "rotate-180")}
          aria-hidden
        />
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchor={anchor}
        label={label}
        align="start"
        width={menuWidth}
        className="p-1.5"
      >
        {withSearch && (
          <label className="mb-1.5 flex h-9 items-center gap-2 rounded-[10px] bg-surface-sunken px-2.5">
            <Search size={14} className="shrink-0 text-ink-faint" aria-hidden />
            <input
              ref={search}
              aria-label={`بحث في ${label}`}
              aria-controls={listId}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setCursor(0);
              }}
              onKeyDown={onKey}
              placeholder="بحث…"
              className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-faint"
            />
          </label>
        )}
        <ul
          ref={list}
          id={listId}
          role="listbox"
          aria-label={label}
          tabIndex={-1}
          onKeyDown={onKey}
          className="max-h-[320px] overflow-y-auto outline-none"
        >
          {filtered.map((option, index) => {
            const active = option.value === value;
            const OptionIcon = option.icon;
            return (
              <li key={option.value} role="presentation">
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  data-index={index}
                  tabIndex={-1}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => choose(option)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-start text-sm transition-colors",
                    index === cursor ? "bg-violet-soft" : "",
                    active ? "font-semibold text-violet-deep" : "text-ink",
                  )}
                >
                  {OptionIcon && <OptionIcon size={15} className="shrink-0 text-violet" aria-hidden />}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{option.label}</span>
                    {option.hint && (
                      <span className="block truncate text-xs font-normal text-ink-faint">{option.hint}</span>
                    )}
                  </span>
                  <Check
                    size={15}
                    className={cn("shrink-0 text-violet", active ? "opacity-100" : "opacity-0")}
                    aria-hidden
                  />
                </button>
              </li>
            );
          })}
          {filtered.length === 0 && (
            <li className="px-3 py-4 text-center text-sm text-ink-faint">لا توجد نتائج</li>
          )}
        </ul>
      </Popover>
    </>
  );
}
