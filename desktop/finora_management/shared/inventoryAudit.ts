import { z } from "zod";
const nullableNumber = z.number().nullable();
export const auditLocationSchema = z.object({
  key: z.string(),
  name: z.string(),
  branch_name: z.string(),
  branch_id: z.number().int(),
  warehouse_id: nullableNumber,
});
export type AuditLocation = z.infer<typeof auditLocationSchema>;
export const auditValuationSchema = z.object({
  method: z.literal("fifo_on_hand_basis_v1"),
  fingerprint: z.string().regex(/^[a-f0-9]{64}$/),
  affected_lines: z.number().int().nonnegative(),
  removed_units: z.number().int().nonnegative(),
  added_units: z.number().int().nonnegative(),
  note: z.string(),
  items: z.array(
    z.object({
      line_id: z.number().int(),
      location_key: z.string(),
      product_name: z.string(),
      variant_name: z.string(),
      system_quantity: z.number(),
      counted_quantity: z.number(),
      layer_quantity_before: z.number(),
      layer_value_before: z.number(),
      layer_value_after: z.number(),
      removed_quantity: z.number(),
      removed_value: z.number(),
      added_quantity: z.number(),
      added_value: z.number(),
    }),
  ),
});
export const auditSessionSchema = z.object({
  id: z.number().int(),
  number: z.string(),
  title: z.string(),
  ledger_kind: z.enum(["branch", "warehouse"]),
  locations: z.array(auditLocationSchema),
  status: z.enum(["counting", "paused", "pending_review", "approved", "posted"]),
  version: z.number().int(),
  created_by: z.number().int(),
  created_by_name: z.string(),
  created_at: z.string(),
  submitted_at: z.string().nullable(),
  approved_by: nullableNumber,
  approved_at: z.string().nullable(),
  posted_by: nullableNumber,
  posted_at: z.string().nullable(),
  review_note: z.string(),
  valuation_review: auditValuationSchema.optional(),
  stats: z.object({
    planned: z.number(),
    counted: z.number(),
    uncounted: z.number(),
    excluded: z.number(),
    unreviewed: z.number().optional(),
    matched: z.number().optional(),
    shortage: z.number().optional(),
    surplus: z.number().optional(),
    shortage_units: z.number().optional(),
    surplus_units: z.number().optional(),
    net_units: z.number().optional(),
  }),
});
export type AuditSession = z.infer<typeof auditSessionSchema>;
export const auditLineSchema = z.object({
  id: z.number().int(),
  location_key: z.string(),
  branch_id: z.number().int(),
  warehouse_id: nullableNumber,
  product: z.object({
    id: z.number().int(),
    name: z.string(),
    sku: z.string(),
    barcode: z.string(),
    current_barcode: z.string().optional(),
    current_sku: z.string().optional(),
    image_url: z.string(),
    model: z.string(),
    variant_id: z.number().int(),
    variant_name: z.string(),
    unit: z.string(),
    unit_cost: z.number().optional(),
  }),
  version: z.number().int(),
  counted_quantity: nullableNumber,
  expected_quantity: nullableNumber,
  baseline_quantity: nullableNumber,
  current_quantity: nullableNumber,
  difference: nullableNumber,
  status: z.enum(["uncounted", "counted", "excluded", "conflict", "matched", "shortage", "surplus"]),
  conflict: z.boolean(),
  counted_at: z.string().nullable(),
  counted_by: nullableNumber,
  notes: z.string(),
  excluded: z.boolean(),
  resolution: z.string(),
  resolution_note: z.string(),
  reviewed_by: nullableNumber,
  reviewed_at: z.string().nullable(),
  posted_delta: nullableNumber,
  posted_cost: nullableNumber,
  movement_id: nullableNumber,
  journal_entry_id: nullableNumber,
  count_open: z.boolean().optional(),
  count_open_by: nullableNumber.optional(),
});
export type AuditLine = z.infer<typeof auditLineSchema>;
export const linePageSchema = z.object({
  items: z.array(auditLineSchema),
  page: z.number(),
  page_size: z.number(),
  total: z.number(),
  total_pages: z.number(),
});
export const commandSchema = z.object({
  session_id: z.number().int(),
  line_id: z.number().int().optional(),
  version: z.number().int().optional(),
  ticket: z.string().optional(),
  started_at: z.string().optional(),
  expected_quantity: z.number().optional(),
  concurrent_counts: z.number().optional(),
  queued: z.boolean().optional(),
  transfer_id: z.number().optional(),
  transfer_kind: z.enum(["branch", "warehouse"]).optional(),
});
export type AuditCommandResult = z.infer<typeof commandSchema>;
export function auditReceiptSchema(action: string) {
  return commandSchema.superRefine((result, ctx) => {
    const fail = () =>
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "incomplete inventory audit receipt" });
    if (result.session_id <= 0) fail();
    if (
      [
        "begin_count",
        "save_count",
        "save_offline_count",
        "cancel_count",
        "exclude",
        "review_line",
        "investigate",
        "transfer_draft",
      ].includes(action) &&
      (!result.line_id || result.line_id <= 0)
    )
      fail();
    if (
      [
        "begin_count",
        "save_count",
        "save_offline_count",
        "cancel_count",
        "submit",
        "approve",
        "post",
        "reopen",
        "pause",
        "resume",
      ].includes(action) &&
      (!result.version || result.version <= 0)
    )
      fail();
    if (
      action === "begin_count" &&
      (!result.ticket || !z.string().uuid().safeParse(result.ticket).success || !result.started_at)
    )
      fail();
    if (action === "transfer_draft" && (!result.transfer_id || !result.transfer_kind)) fail();
  });
}
export type AuditCommand = {
  idempotency_key: string;
  action:
    | "begin_count"
    | "save_count"
    | "cancel_count"
    | "release_ticket"
    | "prepare_offline"
    | "save_offline_count"
    | "transfer_draft"
    | "exclude"
    | "review_line"
    | "submit"
    | "pause"
    | "resume"
    | "reopen"
    | "approve"
    | "post"
    | "investigate";
  line_id?: number;
  version?: number;
  ticket?: string;
  quantity?: number;
  notes?: string;
  reason?: string;
  resolution?: "loss" | "surplus" | "unexplained";
  excluded?: boolean;
  acknowledge_partial?: boolean;
  line_ids?: number[];
  counted_at?: string;
  target_line_id?: number;
  acknowledge_draft?: boolean;
  reconcile_valuation?: boolean;
  valuation_fingerprint?: string;
  valuation_reason?: string;
};

export const auditBase = "/api/v1/desktop/inventory-audits";
/** Query callbacks may outlive their selection; fail before dispatching an invalid request. */
export function auditRequired<T>(value: T | null | undefined): T {
  if (value == null) throw Error("تعذر تحديد سجل الجرد؛ حدّث الصفحة وأعد الاختيار");
  return value;
}
export function auditContext(session: {
  tenant: { slug: string; id: number | null };
  user: { id: number; username: string };
  branch: { id: number } | null;
  branch_scope?: string;
}) {
  return {
    tenant_slug: session.tenant.slug,
    tenant_id: session.tenant.id,
    actor_id: session.user.id,
    branch_id: session.branch?.id ?? null,
    branch_scope: session.branch_scope ?? "branch",
  };
}
export const auditPath =
  /^\/api\/v1\/desktop\/inventory-audits(?:\/(?:meta|local\/status|local\/actions|\d+(?:\/(?:commands|lines|history)|\/lines\/\d+\/(?:details|movements))?))?$/;
export const isAuditCommand = (request: { method: string; path: string }) =>
  request.method === "POST" &&
  (request.path === auditBase || /^\/api\/v1\/desktop\/inventory-audits\/\d+\/commands$/.test(request.path));
export const preparedAuditSchema = commandSchema.extend({
  snapshot: auditSessionSchema,
  snapshot_permissions: z.array(z.string()),
  records: z.array(
    z.object({
      line: auditLineSchema,
      ticket: z.string().uuid(),
      version: z.number().int().positive(),
      issued_at: z.string().datetime({ offset: true }),
      expected_quantity: z.number().optional(),
    }),
  ),
});
export const auditLocalSchema = z.object({
  available: z.boolean(),
  offline: z.boolean(),
  prepared_records: z.number(),
  items: z.array(
    z.object({
      key: z.string().uuid(),
      session_id: z.number().nullable(),
      line_id: z.number().nullable(),
      action: z.string(),
      created: z.number(),
      state: z.enum(["pending", "uncertain", "confirmed", "conflict"]),
      error: z.string().nullable(),
    }),
  ),
});
export const auditLocalAction = z.discriminatedUnion("operation", [
  z.object({ operation: z.literal("retry"), key: z.string().uuid() }).strict(),
  z
    .object({
      operation: z.literal("discard"),
      key: z.string().uuid(),
      reason: z.string().trim().min(1).max(2000),
    })
    .strict(),
  z
    .object({ operation: z.literal("ack"), key: z.string().uuid(), path: z.string(), scope: z.string() })
    .strict(),
]);
const referenceSchema = z.object({
  kind: z.string().optional(),
  id: z.number().optional(),
  number: z.string().optional(),
  line_id: z.number().optional(),
  location_key: z.string().optional(),
  quantity: z.number().optional(),
  status: z.string().optional(),
  payment_status: z.string().nullable().optional(),
  agent_name: z.string().optional(),
  stock_applied: z.boolean().optional(),
  outgoing_movements: z.number().optional(),
  incoming_movements: z.number().optional(),
  from_location: z.string().optional(),
  to_location: z.string().optional(),
});
export const investigationSchema = z.object({
  classification: z.enum(["conflict", "possible", "unexplained", "matched"]),
  message: z.string(),
  difference: z.number(),
  system_quantity: z.number(),
  counted_quantity: z.number(),
  current_quantity: z.number(),
  comparisons: z.array(
    z.object({
      line_id: z.number(),
      location_key: z.string(),
      system_quantity: z.number(),
      counted_quantity: nullableNumber,
      difference: nullableNumber,
      observed: z.boolean(),
      conflict: z.boolean(),
    }),
  ),
  evidence: z.array(
    z.object({
      kind: z.string(),
      classification: z.string(),
      message: z.string(),
      references: z.array(referenceSchema),
    }),
  ),
  company_comparison: z.object({
    scope: z.literal("session"),
    complete: z.boolean(),
    system_total: nullableNumber,
    counted_total: nullableNumber,
    net_difference: nullableNumber,
    note: z.string(),
  }),
  coverage: z.record(z.string()),
  actions: z.array(z.string()),
  auto_transfer: z.literal(false),
});
export type AuditInvestigation = z.infer<typeof investigationSchema>;
export const historySchema = z.object({
  items: z.array(
    z.object({
      id: z.number(),
      line_id: nullableNumber,
      action: z.string(),
      actor_id: z.number(),
      actor_name: z.string(),
      created_at: z.string(),
      detail: z.record(z.unknown()),
    }),
  ),
  page: z.number(),
  page_size: z.number(),
  total: z.number(),
});
export const movementSchema = z.object({
  items: z.array(
    z.object({
      id: z.number(),
      kind: z.string(),
      quantity: z.number(),
      before: nullableNumber,
      after: nullableNumber,
      created_at: z.string(),
      actor_id: nullableNumber,
      reason: z.string().nullable(),
      source_type: z.string().nullable(),
      source_id: nullableNumber,
      unit_cost: z.number().nullable().optional(),
      total_cost: z.number().optional(),
    }),
  ),
  next_before_id: nullableNumber,
});
