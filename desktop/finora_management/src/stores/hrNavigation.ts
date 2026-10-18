import { create } from "zustand";
export interface HRTarget {
  tab: string;
  person_id: number | null;
  date: string;
  month: string | null;
}
export const useHRNavigation = create<{ target: HRTarget | null; set(target: HRTarget | null): void }>(
  (set) => ({
    target: null,
    set: (target) => set({ target }),
  }),
);
