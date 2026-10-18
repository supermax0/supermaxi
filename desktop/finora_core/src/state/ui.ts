import { create } from "zustand";
import type { ConversationFilter } from "../data/source";

export type View = "orb" | "workspace";
export type Overlay = "none" | "activity" | "settings";
export type AnimationQuality = "high" | "balanced" | "low";

export interface Appearance {
  quality: AnimationQuality;
  reducedMotion: "system" | "on" | "off";
}

const APPEARANCE_KEY = "finora-core.appearance";

function loadAppearance(): Appearance {
  const fallback: Appearance = { quality: "high", reducedMotion: "system" };
  try {
    const raw = localStorage.getItem(APPEARANCE_KEY);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return fallback;
    const p = parsed as Record<string, unknown>;
    const quality = p.quality === "balanced" || p.quality === "low" ? p.quality : "high";
    const reducedMotion = p.reducedMotion === "on" || p.reducedMotion === "off" ? p.reducedMotion : "system";
    return { quality, reducedMotion };
  } catch (err) {
    console.warn("[finora-core] appearance settings unreadable, using defaults", err);
    return fallback;
  }
}

interface UiState {
  view: View;
  overlay: Overlay;
  selectedConversationId: string | null;
  customerPanelOpen: boolean;
  channel: "all" | "instagram" | "facebook" | "telegram";
  filter: ConversationFilter;
  search: string;
  appearance: Appearance;
  openWorkspace: (conversationId?: string | null) => void;
  closeWorkspace: () => void;
  setOverlay: (o: Overlay) => void;
  select: (id: string) => void;
  toggleCustomerPanel: (open?: boolean) => void;
  setChannel: (c: UiState["channel"]) => void;
  setFilter: (f: ConversationFilter) => void;
  setSearch: (s: string) => void;
  setAppearance: (a: Partial<Appearance>) => void;
}

export const useUi = create<UiState>((set, get) => ({
  view: "orb",
  overlay: "none",
  selectedConversationId: null,
  customerPanelOpen: true,
  channel: "all",
  filter: "all",
  search: "",
  appearance: loadAppearance(),
  openWorkspace: (conversationId) =>
    set({
      view: "workspace",
      overlay: "none",
      // Preserve the previous selection when reopening (spec §9).
      selectedConversationId: conversationId ?? get().selectedConversationId,
    }),
  closeWorkspace: () => set({ view: "orb" }),
  setOverlay: (overlay) => set({ overlay }),
  select: (id) => set({ selectedConversationId: id }),
  toggleCustomerPanel: (open) => set((s) => ({ customerPanelOpen: open ?? !s.customerPanelOpen })),
  setChannel: (channel) => set({ channel }),
  setFilter: (filter) => set({ filter }),
  setSearch: (search) => set({ search }),
  setAppearance: (a) => {
    const appearance = { ...get().appearance, ...a };
    try {
      localStorage.setItem(APPEARANCE_KEY, JSON.stringify(appearance));
    } catch (err) {
      console.warn("[finora-core] could not persist appearance settings", err);
    }
    set({ appearance });
  },
}));
