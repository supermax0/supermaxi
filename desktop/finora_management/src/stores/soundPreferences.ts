import { create } from "zustand";

export const SOUND_STORAGE_KEY = "finora-management:sounds";
export const SOUND_DEFAULTS = { enabled: true, typing: true, volume: 30 };
export function readSoundPreferences() {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(SOUND_STORAGE_KEY) ?? "null");
    if (typeof value === "object" && value !== null) {
      const stored = value as Record<string, unknown>;
      return {
        enabled: typeof stored.enabled === "boolean" ? stored.enabled : SOUND_DEFAULTS.enabled,
        typing: typeof stored.typing === "boolean" ? stored.typing : SOUND_DEFAULTS.typing,
        volume:
          typeof stored.volume === "number" && Number.isFinite(stored.volume)
            ? Math.round(Math.max(0, Math.min(100, stored.volume)))
            : SOUND_DEFAULTS.volume,
      };
    }
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[sound] preferences unavailable", error);
  }
  return { ...SOUND_DEFAULTS };
}
interface SoundPreferences {
  enabled: boolean;
  typing: boolean;
  volume: number;
  update(patch: Partial<Pick<SoundPreferences, "enabled" | "typing" | "volume">>): void;
}
export const useSoundPreferences = create<SoundPreferences>((set, get) => ({
  ...readSoundPreferences(),
  update(patch) {
    const current = get();
    const next = {
      enabled: typeof patch.enabled === "boolean" ? patch.enabled : current.enabled,
      typing: typeof patch.typing === "boolean" ? patch.typing : current.typing,
      volume:
        typeof patch.volume === "number" && Number.isFinite(patch.volume)
          ? Math.round(Math.max(0, Math.min(100, patch.volume)))
          : current.volume,
    };
    set(next);
    try {
      localStorage.setItem(SOUND_STORAGE_KEY, JSON.stringify(next));
    } catch (error) {
      if (import.meta.env.DEV) console.debug("[sound] preferences not saved", error);
    }
  },
}));
