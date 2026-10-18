/** Per-device UI conveniences. Stored in localStorage best-effort; the app works without it. */
import { create } from "zustand";

export type MotionPreference = "system" | "reduced";

const STORAGE_KEY = "finora-management:preferences";

function readMotion(): MotionPreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return "system";
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      (parsed as { motion?: unknown }).motion === "reduced"
    ) {
      return "reduced";
    }
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[preferences] unavailable", error);
  }
  return "system";
}

function writeMotion(motion: MotionPreference): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ motion }));
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[preferences] not persisted", error);
  }
}

interface PreferencesState {
  motion: MotionPreference;
  setMotion(motion: MotionPreference): void;
}

export const usePreferences = create<PreferencesState>()((set) => ({
  motion: readMotion(),
  setMotion(motion) {
    writeMotion(motion);
    set({ motion });
  },
}));
