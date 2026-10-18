import { create } from "zustand";
import { useSession } from "./session";

/** One-shot native navigation from a customer or another source document. */
export const useOrderNavigation = create<{ invoiceId: number | null; open(id: number): void; clear(): void }>(
  (set) => ({
    invoiceId: null,
    open: (invoiceId) => set({ invoiceId }),
    clear: () => set({ invoiceId: null }),
  }),
);

useSession.subscribe((current, previous) => {
  const scope = (state: typeof current) =>
    state.session
      ? `${state.session.tenant.slug}:${state.session.user.id}:${state.session.branch?.id ?? "all"}`
      : "";
  if (scope(current) !== scope(previous)) useOrderNavigation.getState().clear();
});
