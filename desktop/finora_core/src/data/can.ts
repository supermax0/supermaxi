import { useSource } from "./hooks";
import { HttpDataSource } from "./http";

export type Permission =
  | "conversations.view"
  | "messages.send"
  | "ai.takeover"
  | "notes.write"
  | "tenants.create"
  | "approvals.decide"
  | "audit.view"
  | "settings.manage";

/** UI gating mirrors server RBAC (the server still enforces every permission). Dev data has full access. */
export function useCan(permission: Permission): boolean {
  const src = useSource();
  if (src instanceof HttpDataSource) return src.operator.permissions.includes(permission);
  return true;
}
