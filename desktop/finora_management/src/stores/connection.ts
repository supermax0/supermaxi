/**
 * FINORA reachability. "offline" = the OS reports no network; "unreachable" =
 * the network is up but FINORA did not answer. Sensitive writes must check
 * `canMutate()` and stay disabled while not online.
 */
import { create } from "zustand";

export type ConnectionStatus = "online" | "offline" | "unreachable";

interface ConnectionState {
  status: ConnectionStatus;
  since: number;
  setStatus(status: ConnectionStatus): void;
}

export const useConnection = create<ConnectionState>()((set, get) => ({
  status: typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "online",
  since: Date.now(),
  setStatus(status) {
    if (get().status !== status) set({ status, since: Date.now() });
  },
}));

export function canMutate(): boolean {
  return useConnection.getState().status === "online";
}
