import { z } from "zod";
import type { FinoraRequest, FinoraResponse } from "./ipc";

const PREFIX = "/api/v1/desktop/customers";
export function isCustomerCommand(request: FinoraRequest): boolean {
  if (request.method !== "POST") return false;
  try {
    return new RegExp(`^${PREFIX}(/|$)`).test(decodeURIComponent(request.path));
  } catch {
    return request.path.startsWith(PREFIX);
  }
}
export function customerCommandPath(path: string): boolean {
  return (
    path === `${PREFIX}/commands` ||
    /^\/api\/v1\/desktop\/customers\/[1-9]\d*\/(debts|invoices\/[1-9]\d*\/schedule|plans\/[1-9]\d*\/(schedule|repartition))$/.test(
      path,
    )
  );
}
export const customerCommandKey = z.string().uuid();
export const customerAcknowledgement = z
  .object({
    key: customerCommandKey,
    path: z.string().max(300),
    scope: z.string().regex(/^[a-f0-9]{64}$/),
  })
  .strict();
export interface SavedCustomerCommand {
  key: string;
  request: FinoraRequest;
  created: number;
  state: "uncertain" | "confirmed";
}
export interface CustomerRecoveryBridge {
  list(): Promise<{ available: boolean; items: SavedCustomerCommand[]; error?: string }>;
  retry(key: string): Promise<{ request: FinoraRequest; response: FinoraResponse }>;
  acknowledge(input: { key: string; path: string; scope: string }): Promise<void>;
}
