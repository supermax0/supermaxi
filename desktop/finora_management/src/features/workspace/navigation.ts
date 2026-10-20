import { useEffect, useRef } from "react";
import { create } from "zustand";
import { useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import type { WindowId } from "@/windows/registry";
import { allowedWindow, useWorkspace, type ActionId, type WorkspaceTarget } from "./state";
export const useLiveWorkspaceTarget = create<{
  target: WorkspaceTarget | null;
  setTarget(target: WorkspaceTarget): void;
}>()((set) => ({ target: null, setTarget: (target) => set({ target }) }));

export const ACTION_TARGETS: Record<ActionId, WindowId | null> = {
  order: "pos",
  sale: "pos",
  expense: "expenses",
  receipt: "finance",
  audit: "products",
  search: null,
  product: "products",
  customer: "customers",
};
export function actionAllowed(id: ActionId): boolean {
  const session = useSession.getState().session;
  const can = (p: string) => session?.permissions.some((x) => x === p) ?? false;
  const window = ACTION_TARGETS[id];
  if (window && !allowedWindow(window, session)) return false;
  if (id === "receipt") return can("finance.create");
  if (id === "audit") return can("inventory.audit.view");
  if (id === "product") return can("can_manage_inventory");
  return !!session;
}
export function openWorkspaceTarget(target: WorkspaceTarget, action?: ActionId): void {
  if (!allowedWindow(target.window, useSession.getState().session) || (action && !actionAllowed(action))) {
    toast.error("لم تعد لديك صلاحية لفتح هذا القسم");
    return;
  }
  useWorkspace.getState().navigate(target, action);
  useWindowManager.getState().open(target.window);
}
export function runWorkspaceAction(action: ActionId): void {
  if (!actionAllowed(action)) return;
  if (action === "search") {
    useUi.getState().setPaletteOpen(true);
    return;
  }
  const window = ACTION_TARGETS[action];
  if (window) openWorkspaceTarget({ window }, action);
}
/** One-shot commands use the existing mounted window; no transaction is ever replayed. */
export function useWorkspaceRequest(
  id: WindowId,
  handle: (target: WorkspaceTarget, action?: ActionId) => void,
  ready = true,
): void {
  const request = useWorkspace((s) => s.requests[id]);
  const active = useWindowManager((s) => s.active === id);
  const handler = useRef(handle);
  handler.current = handle;
  useEffect(() => {
    if (!ready || !active || request?.target.window !== id) return;
    useWorkspace.getState().consume(id);
    if (!allowedWindow(id, useSession.getState().session)) return;
    handler.current(request.target, request.action);
  }, [id, active, request, ready]);
}
/** Filters/record IDs only: customer names, searches and draft form fields stay out of recovery. */
export function useWorkspaceHistory(target: WorkspaceTarget, enabled = true): void {
  const active = useWindowManager((s) => s.active === target.window);
  const ready = useWorkspace((s) => s.ready);
  const scope = useWorkspace((s) => s.scope);
  const serialized = JSON.stringify(target);
  useEffect(() => {
    if (enabled && active)
      useLiveWorkspaceTarget.getState().setTarget(JSON.parse(serialized) as WorkspaceTarget);
  }, [active, enabled, serialized]);
  useEffect(() => {
    if (!enabled || !active || !ready) return;
    const timer = window.setTimeout(
      () => useWorkspace.getState().record(JSON.parse(serialized) as WorkspaceTarget),
      250,
    );
    return () => window.clearTimeout(timer);
  }, [active, ready, scope, serialized, enabled]);
}
