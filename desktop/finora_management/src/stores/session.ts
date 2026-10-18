import { create } from "zustand";
import type { FinoraSession, Permission } from "@/api/finora";

export type SignedOutReason = "signed_out" | "expired" | "password_change_required" | null;

interface SessionState {
  status: "unknown" | "signed_in" | "signed_out";
  session: FinoraSession | null;
  reason: SignedOutReason;
  signedIn(session: FinoraSession): void;
  signedOut(reason: SignedOutReason): void;
}

export const useSession = create<SessionState>()((set) => ({
  status: "unknown",
  session: null,
  reason: null,
  signedIn(session) {
    set({ status: "signed_in", session, reason: null });
  },
  signedOut(reason) {
    set({ status: "signed_out", session: null, reason });
  },
}));

/** Mirrors FINORA's RBAC for showing/hiding actions; FINORA still enforces every call. */
export function useCan(permission: Permission): boolean {
  return useSession((s) => s.session?.permissions.includes(permission) ?? false);
}
