import { create } from "zustand";

export type TopPanel = "notifications" | "settings" | "more" | null;

interface UiState {
  panel: TopPanel;
  paletteOpen: boolean;
  settingsTarget: "offline" | null;
  openOfflineSettings(): void;
  clearSettingsTarget(): void;
  togglePanel(panel: Exclude<TopPanel, null>): void;
  closePanel(): void;
  setPaletteOpen(open: boolean): void;
}

export const useUi = create<UiState>()((set, get) => ({
  panel: null,
  paletteOpen: false,
  settingsTarget: null,
  openOfflineSettings() {
    set({ panel: "settings", paletteOpen: false, settingsTarget: "offline" });
  },
  clearSettingsTarget() {
    set({ settingsTarget: null });
  },
  togglePanel(panel) {
    set({ panel: get().panel === panel ? null : panel, paletteOpen: false });
  },
  closePanel() {
    if (get().panel !== null) set({ panel: null });
  },
  setPaletteOpen(open) {
    set({ paletteOpen: open, panel: open ? null : get().panel });
  },
}));

/** True while an overlay owns the keyboard (Escape must close it, not the active window). */
export function overlayOpen(): boolean {
  const { panel, paletteOpen } = useUi.getState();
  return panel !== null || paletteOpen;
}
