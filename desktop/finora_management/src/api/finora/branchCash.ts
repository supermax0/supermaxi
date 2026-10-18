import { z } from "zod";
import { finoraCall } from "./transport";

/** Branch cash transfers — modules/desktop_api/branch_cash.py over utils/branch_cash_transfers. */
const BASE = "/api/v1/desktop/branch-cash";
const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ ok: z.literal(true), ...shape });

export const CASH_STATUSES = [
  "pending",
  "approved",
  "posting",
  "completed",
  "rejected",
  "cancelled",
] as const;
export type CashStatus = (typeof CASH_STATUSES)[number];

const eventSchema = z.object({
  action: z.string(),
  name: z.string().optional(),
  at: z.string(),
  status: z.string().optional(),
  reason: z.string().optional(),
});

export const cashTransferSchema = z.object({
  id: z.number().int(),
  number: z.string(),
  status: z.enum(CASH_STATUSES),
  status_label: z.string(),
  amount: z.number(),
  currency: z.string(),
  from_account: z.string(),
  to_account: z.string(),
  from_branch: z.string(),
  to_branch: z.string(),
  from_branch_id: z.number().int(),
  to_branch_id: z.number().int(),
  transfer_date: z.string(),
  reference: z.string(),
  reason: z.string(),
  notes: z.string(),
  requested_by: z.string(),
  approved_by: z.string(),
  received_by: z.string(),
  closed_reason: z.string(),
  created_at: z.string(),
  completed_at: z.string(),
  posted: z.boolean(),
  events: z.array(eventSchema),
  can_approve: z.boolean().optional(),
  can_receive: z.boolean().optional(),
  can_reject: z.boolean().optional(),
  can_cancel: z.boolean().optional(),
});
export type CashTransfer = z.infer<typeof cashTransferSchema>;

const pendingSchema = z.object({ count: z.number().int(), amount: z.number() });
const accountSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  type: z.string(),
  branch_id: z.number().int(),
  branch_name: z.string(),
  can_send_from: z.boolean(),
  /** null = another branch's balance, hidden from a non-admin. */
  balance: z.number().nullable(),
});
export type CashAccount = z.infer<typeof accountSchema>;

export interface CashTransferInput {
  from_account_id: number;
  to_account_id: number;
  amount: number;
  reason: string;
  reference?: string;
  notes?: string;
  operation_id: string;
  execute_now?: boolean;
}

const envelope = ok({ transfer: cashTransferSchema });

export const branchCash = {
  meta: () =>
    finoraCall(
      { method: "GET", path: `${BASE}/meta` },
      ok({ accounts: z.array(accountSchema), can_execute_now: z.boolean(), pending: pendingSchema }),
    ),
  list: (status: string, search: string) =>
    finoraCall(
      { method: "GET", path: BASE, query: { status, search: search.trim() } },
      ok({ rows: z.array(cashTransferSchema), pending: pendingSchema }),
    ),
  create: (input: CashTransferInput) =>
    finoraCall({ method: "POST", path: BASE, body: { ...input }, timeoutMs: 30_000 }, envelope),
  act: (id: number, action: "approve" | "receive" | "reject" | "cancel", reason = "") =>
    finoraCall(
      { method: "POST", path: `${BASE}/${id}/${action}`, body: { reason }, timeoutMs: 30_000 },
      envelope,
    ),
};
