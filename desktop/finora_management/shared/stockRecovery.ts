import type { FinoraRequest } from "./ipc";
import type { FinoraSession } from "../src/api/finora/schemas";
const prefix = "/api/v1/desktop/stock-operations";
export function isStockCommand(request: FinoraRequest): boolean {
  if (request.method !== "POST") return false;
  try {
    return decodeURIComponent(request.path).startsWith(`${prefix}/`);
  } catch {
    return request.path.startsWith(`${prefix}/`);
  }
}
export function stockCommandPath(path: string): boolean {
  return (
    /^\/api\/v1\/desktop\/stock-operations\/(?:branch|warehouse)\/(?:transfers(?:\/[1-9]\d*\/(?:send|receive|cancel))?|writeoffs|rules)$/.test(
      path,
    ) ||
    /^\/api\/v1\/desktop\/stock-operations\/writeoffs\/[1-9]\d*\/reverse$/.test(path) ||
    path === `${prefix}/warehouse/locations` ||
    /^\/api\/v1\/desktop\/stock-operations\/storage\/(?:locations(?:\/[1-9]\d*)?|transfers(?:\/[1-9]\d*\/(?:send|receive|cancel))?)$/.test(
      path,
    )
  );
}
export function stockCommandAllowed(session: FinoraSession, path: string): boolean {
  const permissions = session.permissions;
  if (!permissions.includes("can_manage_inventory")) return false;
  if (!path) return true;
  if (!stockCommandPath(path)) return false;
  if (path.includes("/warehouse/") && session.tenant.business_type !== "wholesale") return false;
  if (
    path.includes("/warehouse/") &&
    session.user.role !== "admin" &&
    !permissions.includes("wholesale_warehouses")
  )
    return false;
  if (path.endsWith("/rules")) return permissions.includes("edit_product");
  if (!permissions.includes("edit_current_stock")) return false;
  if (path.startsWith(`${prefix}/storage/`)) return true;
  if (path.includes("/writeoffs"))
    return permissions.includes("finance.approve") && permissions.includes("finance.view");
  return !/\/(send|cancel)$/.test(path) || session.user.role === "admin";
}
