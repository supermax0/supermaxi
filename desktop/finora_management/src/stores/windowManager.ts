/**
 * Central window manager. Exactly one window is active at a time; switching is
 * a single state change so the open and close morphs always run together and
 * never fight (the transition layer derives everything from `active`).
 */
import { create } from "zustand";
import type { WindowId } from "@/windows/registry";

interface WindowManagerState {
  active: WindowId | null;
  /** Window that most recently left the stage — the transition layer morphs it back to its button. */
  previous: WindowId | null;
  /** Windows sent back to their button with "minimize" (shown as a dot on the button). */
  minimized: ReadonlySet<WindowId>;
  expanded: boolean;
  /** Increases on every change; lets tests and the transition layer detect rapid switching. */
  revision: number;
  open(id: WindowId): void;
  toggle(id: WindowId): void;
  close(): void;
  minimize(): void;
  toggleExpanded(): void;
  reset(): void;
}

const initial = {
  active: null,
  previous: null,
  minimized: new Set<WindowId>(),
  expanded: false,
  revision: 0,
};

export const useWindowManager = create<WindowManagerState>()((set, get) => ({
  ...initial,
  open(id) {
    const { active, minimized, revision } = get();
    if (active === id) return;
    const nextMinimized = new Set(minimized);
    nextMinimized.delete(id);
    set({ active: id, previous: active, minimized: nextMinimized, revision: revision + 1 });
  },
  toggle(id) {
    if (get().active === id) get().close();
    else get().open(id);
  },
  close() {
    const { active, revision } = get();
    if (active === null) return;
    set({ active: null, previous: active, revision: revision + 1 });
  },
  minimize() {
    const { active, minimized, revision } = get();
    if (active === null) return;
    const nextMinimized = new Set(minimized);
    nextMinimized.add(active);
    set({ active: null, previous: active, minimized: nextMinimized, revision: revision + 1 });
  },
  toggleExpanded() {
    set({ expanded: !get().expanded });
  },
  reset() {
    set({ ...initial, minimized: new Set<WindowId>() });
  },
}));
