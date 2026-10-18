import { create } from "zustand";
import type { OfflineStatus } from "@shared/offline";

export const EMPTY_OFFLINE: OfflineStatus = {
  available: false,
  lastVerifiedAt: null,
  lastCachedAt: null,
  pending: 0,
  conflicts: 0,
  syncing: false,
  error: null,
  operations: [],
};
export const useOffline = create<{ status: OfflineStatus; set(status: OfflineStatus): void }>((set) => ({
  status: EMPTY_OFFLINE,
  set: (status) => set({ status }),
}));
