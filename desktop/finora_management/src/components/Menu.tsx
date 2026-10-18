import { AnimatePresence, motion } from "framer-motion";
import { type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/utils/cn";

export interface MenuItem {
  id: string;
  label: string;
  icon: LucideIcon;
  onSelect(): void;
  danger?: boolean;
  disabled?: boolean;
}

interface MenuProps {
  label: string;
  items: MenuItem[];
  /** Renders the trigger; receives the props to spread on a button. */
  trigger(props: {
    ref: (el: HTMLButtonElement | null) => void;
    onClick(): void;
    "aria-expanded": boolean;
  }): ReactNode;
}

const MENU_WIDTH = 220;

/**
 * Dropdown / row context menu. Rendered in a portal with fixed positioning so
 * it is never clipped by the table's scroll container.
 */
export function Menu({ label, items, trigger }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const anchor = useRef<HTMLButtonElement | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);

  useLayoutEffect(() => {
    if (!open || !anchor.current) return;
    const rect = anchor.current.getBoundingClientRect();
    const height = items.length * 42 + 12;
    const below = rect.bottom + 6 + height < window.innerHeight;
    setPosition({
      top: below ? rect.bottom + 6 : Math.max(8, rect.top - height - 6),
      left: Math.min(Math.max(8, rect.left), window.innerWidth - MENU_WIDTH - 8),
    });
  }, [open, items.length]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panel.current?.contains(target) || anchor.current?.contains(target)) return;
      close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    };
    const onScroll = () => close();
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", onScroll);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("scroll", onScroll, true);
    };
  }, [open, close]);

  useEffect(() => {
    if (open) panel.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [open]);

  return (
    <>
      {trigger({
        ref: (element) => {
          anchor.current = element;
        },
        onClick: () => setOpen((value) => !value),
        "aria-expanded": open,
      })}
      {createPortal(
        <AnimatePresence>
          {open && (
            <motion.div
              ref={panel}
              role="menu"
              aria-label={label}
              dir="rtl"
              className="glass-solid fixed z-[80] rounded-control p-1.5"
              style={{ top: position.top, left: position.left, width: MENU_WIDTH }}
              initial={{ opacity: 0, scale: 0.97, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.1 } }}
              transition={{ duration: 0.14, ease: [0.22, 1, 0.36, 1] }}
              onKeyDown={(event) => {
                if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                event.preventDefault();
                const buttons = [
                  ...(panel.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []),
                ];
                const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
                const next = event.key === "ArrowDown" ? index + 1 : index - 1;
                buttons[(next + buttons.length) % buttons.length]?.focus();
              }}
            >
              {items.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="menuitem"
                    disabled={item.disabled}
                    onClick={() => {
                      close();
                      item.onSelect();
                    }}
                    className={cn(
                      "flex h-10 w-full items-center gap-3 rounded-[10px] px-3 text-start text-[13.5px] outline-none transition-colors",
                      "disabled:pointer-events-none disabled:opacity-40",
                      item.danger
                        ? "text-danger hover:bg-danger-soft focus:bg-danger-soft"
                        : "text-ink hover:bg-violet-soft focus:bg-violet-soft",
                    )}
                  >
                    <Icon size={16} strokeWidth={1.8} aria-hidden />
                    {item.label}
                  </button>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
