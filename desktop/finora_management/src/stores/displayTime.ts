import { create } from "zustand";

export type TimeFormat = "12" | "24";
const webConfig = (globalThis as typeof globalThis & { FINORA_TIME_CONFIG?: { format?: string } })
  .FINORA_TIME_CONFIG;
export const useDisplayTime = create<{ format: TimeFormat; setFormat(value: TimeFormat): void }>((set) => ({
  format: webConfig?.format === "24" ? "24" : "12",
  setFormat: (format) => set({ format }),
}));

if (typeof window !== "undefined")
  window.addEventListener("finora:time-format", (event) => {
    const value = (event as CustomEvent<unknown>).detail;
    if (value === "12" || value === "24") useDisplayTime.getState().setFormat(value);
  });

/** Subscribe in components that present dates; changing format never remounts their forms. */
export function useTimeFormat(): TimeFormat {
  return useDisplayTime((state) => state.format);
}
