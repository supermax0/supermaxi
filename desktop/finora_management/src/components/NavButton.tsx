import { motion } from "framer-motion";
import { memo, useCallback } from "react";
import { registerNavAnchor } from "@/animations/anchors";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { WINDOWS, type WindowId } from "@/windows/registry";

export const NavButton = memo(function NavButton({ id }: { id: WindowId }) {
  const definition = WINDOWS[id];
  const active = useWindowManager((s) => s.active === id);
  const minimized = useWindowManager((s) => s.minimized.has(id));
  const toggle = useWindowManager((s) => s.toggle);
  const anchor = useCallback((element: HTMLButtonElement | null) => registerNavAnchor(id, element), [id]);
  const Icon = definition.icon;

  return (
    <button
      ref={anchor}
      type="button"
      data-nav={id}
      aria-pressed={active}
      title={`${definition.title} (Ctrl+${definition.shortcut})`}
      onClick={() => toggle(id)}
      className={cn(
        "no-drag relative flex h-[58px] w-[92px] flex-col items-center justify-center gap-1 rounded-control text-[13px] font-medium",
        "transition-colors duration-200",
        active ? "text-violet-deep" : "text-ink-soft hover:bg-white/70 hover:text-ink",
      )}
    >
      {active && (
        <motion.span
          layoutId="nav-active-pill"
          className="absolute inset-0 rounded-control bg-gradient-to-b from-violet-soft to-white shadow-control ring-1 ring-violet/15"
          transition={{ type: "spring", stiffness: 520, damping: 40 }}
        />
      )}
      <Icon size={21} strokeWidth={1.8} className="relative" aria-hidden />
      <span className="relative">{definition.navLabel}</span>
      {minimized && !active && (
        <span className="absolute bottom-1.5 h-1 w-1 rounded-full bg-violet" aria-label="مصغّرة" />
      )}
    </button>
  );
});
