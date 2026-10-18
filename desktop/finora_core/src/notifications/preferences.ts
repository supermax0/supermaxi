import { create } from "zustand";
import { z } from "zod";

const schema = z.object({
  enabled: z.boolean().default(true),
  mode: z.enum(["live", "chime"]).default("live"),
  volume: z.number().min(0).max(1).default(0.65),
  approvals: z.boolean().default(true),
  important: z.boolean().default(true),
});
export type SoundPreferences = z.infer<typeof schema>;
export type VoiceStatus = "ready" | "locked" | "connecting" | "speaking" | "unavailable";
const KEY = "finora-core.notification-sound";
function load(): SoundPreferences {
  try {
    const result = schema.safeParse(JSON.parse(localStorage.getItem(KEY) ?? "{}"));
    if (result.success) return result.data;
  } catch {
    // Corrupt or inaccessible device preferences fall back to a bounded volume.
  }
  return schema.parse({});
}
export const useSound = create<{
  preferences: SoundPreferences;
  status: VoiceStatus;
  update: (patch: Partial<SoundPreferences>) => void;
}>((set, get) => ({
  preferences: load(),
  status: "locked",
  update: (patch) => {
    const preferences = schema.parse({ ...get().preferences, ...patch });
    try {
      localStorage.setItem(KEY, JSON.stringify(preferences));
    } catch {
      // Keep the preference for this session when device storage is unavailable.
    }
    set({ preferences });
  },
}));
