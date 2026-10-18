import { create } from "zustand";
import { useSession } from "./session";

const scope = () => {
  const session = useSession.getState().session;
  return session
    ? JSON.stringify([
        session.tenant.slug,
        session.user.id,
        session.branch?.id,
        session.branch_scope,
        session.permissions.slice().sort(),
      ])
    : "";
};
export const usePurchaseNavigation = create<{
  target: { id: number; scope: string } | null;
  open(id: number): void;
  clear(): void;
}>((set) => ({
  target: null,
  open: (id) => set({ target: { id, scope: scope() } }),
  clear: () => set({ target: null }),
}));
useSession.subscribe(() => {
  const target = usePurchaseNavigation.getState().target;
  if (target && target.scope !== scope()) usePurchaseNavigation.getState().clear();
});
export const purchaseNavigationScope = scope;
