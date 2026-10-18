import { AnimatePresence, motion } from "framer-motion";
import { CornerDownLeft, Search, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { searchItems } from "@/navigation/search";
import { cn } from "@/utils/cn";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  /** Alternative names / synonyms the shared navigation search also matches. */
  keywords?: readonly string[];
  run(): void;
}

interface CommandPaletteProps {
  open: boolean;
  commands: Command[];
  onClose(): void;
}

/** Ctrl+K quick switcher for windows and app actions. */
export function CommandPalette({ open, commands, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  // Same engine as «المزيد» (navigation/search.ts): Arabic/English, partial words, synonyms, ranked.
  const results = useMemo(() => (query.trim() ? searchItems(commands, query) : commands), [commands, query]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCursor(0);
    const frame = requestAnimationFrame(() => input.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open]);

  const execute = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    command.run();
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((value) => Math.min(value + 1, Math.max(results.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((value) => Math.max(value - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      execute(results[cursor]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="no-drag fixed inset-0 z-[60] flex justify-center bg-ink/10 pt-[14vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.12 } }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.div
            role="dialog"
            aria-label="بحث سريع"
            className="glass-solid h-fit w-[560px] overflow-hidden rounded-panel"
            initial={{ opacity: 0, y: -10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            onKeyDown={onKeyDown}
          >
            <label className="flex items-center gap-3 border-b border-line px-5">
              <Search size={18} className="text-ink-faint" aria-hidden />
              <input
                ref={input}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setCursor(0);
                }}
                placeholder="ابحث عن نافذة أو إجراء…"
                aria-label="بحث"
                className="h-14 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-faint"
              />
              <kbd className="ltr-isolate rounded-md border border-line px-1.5 text-[11px] text-ink-faint">
                Esc
              </kbd>
            </label>
            <ul role="listbox" aria-label="النتائج" className="max-h-[320px] overflow-y-auto p-2">
              {results.length === 0 && (
                <li className="px-4 py-6 text-center text-sm text-ink-faint">لا توجد نتائج مطابقة</li>
              )}
              {results.map((command, index) => {
                const Icon = command.icon;
                return (
                  <li key={command.id} role="option" aria-selected={index === cursor}>
                    <button
                      type="button"
                      onMouseEnter={() => setCursor(index)}
                      onClick={() => execute(command)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-control px-3 py-2.5 text-start text-sm",
                        index === cursor ? "bg-violet-soft text-violet-deep" : "text-ink",
                      )}
                    >
                      <Icon size={18} strokeWidth={1.8} aria-hidden />
                      <span className="flex-1">{command.label}</span>
                      {command.hint && (
                        <span className="ltr-isolate text-xs text-ink-faint">{command.hint}</span>
                      )}
                      {index === cursor && <CornerDownLeft size={14} aria-hidden />}
                    </button>
                  </li>
                );
              })}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
