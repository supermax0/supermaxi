import { create } from "zustand";
import { useSession } from "./session";

export interface CustomerCollection {
  customerId: number;
  customerName: string;
  branchId: number | null;
  invoiceId: number;
  documentKind?: "invoice" | "credit_plan";
  remaining: number;
}

/** One-shot context only; the financial command still validates the live debt and permissions. */
export const useFinanceNavigation = create<{
  collection: CustomerCollection | null;
  voucherId: number | null;
  showVoucher(id: number): void;
  collect(value: CustomerCollection): void;
  clear(): void;
}>((set) => ({
  collection: null,
  voucherId: null,
  showVoucher: (voucherId) => set({ voucherId, collection: null }),
  collect: (collection) => set({ collection, voucherId: null }),
  clear: () => set({ collection: null, voucherId: null }),
}));

useSession.subscribe((current, previous) => {
  const scope = (state: typeof current) =>
    state.session
      ? `${state.session.tenant.slug}:${state.session.user.id}:${state.session.branch?.id ?? "all"}`
      : "";
  if (scope(current) !== scope(previous)) useFinanceNavigation.getState().clear();
});
