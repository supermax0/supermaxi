import { z } from "zod";
import { finoraCall } from "./transport";

const preview = z.object({
  ledger: z.number(),
  expected: z.number(),
  net_movement: z.number(),
  token: z.string(),
  movement_count: z.number(),
  fingerprint: z.string(),
});
const shift = z.object({
  id: z.number(),
  name: z.string(),
  branch_id: z.number(),
  treasury_account_id: z.number(),
  account_name: z.string(),
  status: z.enum(["open", "closed"]),
  version: z.number(),
  opened_by: z.string(),
  closed_by: z.string().nullable(),
  opened_at: z.string(),
  closed_at: z.string().nullable(),
  opening_actual: z.number(),
  opening_ledger: z.number(),
  opening_variance: z.number(),
  opening_reason: z.string(),
  actual: z.number().nullable(),
  ledger: z.number().nullable(),
  expected: z.number().nullable(),
  variance: z.number().nullable(),
  reason: z.string(),
  preview: preview.optional(),
  ledger_changed_since_close: z.boolean().optional(),
});
export type CashShift = z.infer<typeof shift>;
const envelope = <T extends z.ZodTypeAny>(schema: T) =>
  z.object({ success: z.literal(true), data: schema }).transform((r) => r.data);
export const cashShifts = {
  list: (page: number, status: string, pageSize: number) =>
    finoraCall(
      { method: "GET", path: "/api/finance/cash-shifts", query: { page, status, page_size: pageSize } },
      envelope(
        z.object({ items: z.array(shift), total: z.number(), page: z.number(), page_size: z.number() }),
      ),
    ),
  details: (id: number) =>
    finoraCall({ method: "GET", path: `/api/finance/cash-shifts/${id}` }, envelope(shift)),
  command: (
    operation: "cash_shift.open" | "cash_shift.close",
    body: Record<string, string | number>,
    key: string,
  ) =>
    finoraCall(
      { method: "POST", path: "/api/finance/commands", body: { ...body, operation, idempotency_key: key } },
      envelope(shift),
    ),
};
