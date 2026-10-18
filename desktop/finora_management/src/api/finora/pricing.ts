import { z } from "zod";
import { finoraCall, finoraForm } from "./transport";

/** Selling-price engine — modules/pricing over /api/v1/desktop/pricing. Never touches stock value or invoices. */
const BASE = "/api/v1/desktop/pricing";
const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ success: z.literal(true), ...shape });

const ruleSchema = z.object({
  id: z.number().int(),
  scope: z.enum(["default", "category", "brand", "product"]),
  scope_value: z.string(),
  target_margin_pct: z.number(),
  minimum_margin_pct: z.number(),
  extra_cost: z.number(),
  rounding_step: z.number(),
  automatic: z.boolean(),
  max_auto_change_pct: z.number(),
  approval_required: z.boolean(),
  active: z.boolean(),
});
export type PriceRule = z.infer<typeof ruleSchema>;
export type PriceRuleInput = Omit<PriceRule, "id">;

const batchSchema = z.object({
  id: z.number().int(),
  label: z.string(),
  source: z.string(),
  status: z.enum(["draft", "applied", "rejected"]),
  counts: z.record(z.number()),
  net_change_per_unit: z.number(),
  rows: z.array(
    z.object({
      id: z.number().int(),
      product_id: z.number().int().nullable(),
      name: z.string(),
      ref: z.string(),
      old_price: z.number().nullable(),
      new_price: z.number().nullable(),
      cost_basis: z.number().nullable(),
      minimum_price: z.number().nullable(),
      verdict: z.enum(["up", "down", "same", "below_minimum", "unmatched", "invalid"]),
      note: z.string(),
      applied: z.boolean(),
    }),
  ),
});
export type PriceBatch = z.infer<typeof batchSchema>;

const promotionSchema = z.object({
  id: z.number().int(),
  product_id: z.number().int(),
  product_name: z.string().optional().default(""),
  promo_price: z.number(),
  regular_price: z.number().nullable(),
  starts_at: z.string(),
  ends_at: z.string(),
  status: z.enum(["scheduled", "running", "ended", "cancelled", "conflict"]),
  note: z.string(),
});
export type Promotion = z.infer<typeof promotionSchema>;

export const pricing = {
  rules: () => finoraCall({ method: "GET", path: `${BASE}/rules` }, ok({ rows: z.array(ruleSchema) })),
  saveRule: (id: number | null, input: PriceRuleInput) =>
    finoraCall(
      { method: "POST", path: id ? `${BASE}/rules/${id}` : `${BASE}/rules`, body: { ...input } },
      ok({ rule: ruleSchema }),
    ),
  fromRules: () =>
    finoraCall(
      { method: "POST", path: `${BASE}/batches/from-rules`, body: {}, timeoutMs: 60_000 },
      ok({ batch: batchSchema }),
    ),
  fromFile: (
    file: {
      name: string;
      type: "text/csv" | "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
      data: Uint8Array;
    },
    supplier: string,
  ) =>
    finoraForm(
      {
        path: `${BASE}/batches/from-file`,
        fields: [["supplier", supplier]],
        file: { field: "file", ...file },
        timeoutMs: 60_000,
      },
      ok({ batch: batchSchema }),
    ),
  approve: (id: number) =>
    finoraCall(
      { method: "POST", path: `${BASE}/batches/${id}/approve`, body: {}, timeoutMs: 60_000 },
      ok({ result: z.object({ applied: z.number(), stale: z.number(), skipped: z.number() }) }),
    ),
  reject: (id: number) =>
    finoraCall({ method: "POST", path: `${BASE}/batches/${id}/reject`, body: {} }, ok({})),
  runAutomatic: () =>
    finoraCall(
      { method: "POST", path: `${BASE}/automatic/run`, body: {}, timeoutMs: 60_000 },
      ok({ result: z.object({ applied: z.number(), needs_approval: z.number() }) }),
    ),
  promotions: () =>
    finoraCall({ method: "GET", path: `${BASE}/promotions` }, ok({ rows: z.array(promotionSchema) })),
  createPromotion: (input: {
    product_id: number;
    promo_price: number;
    starts_at: string;
    ends_at: string;
    note?: string;
  }) =>
    finoraCall(
      { method: "POST", path: `${BASE}/promotions`, body: { ...input } },
      ok({ id: z.number().int(), status: z.string() }),
    ),
  cancelPromotion: (id: number) =>
    finoraCall(
      { method: "POST", path: `${BASE}/promotions/${id}/cancel`, body: {} },
      ok({ status: z.string() }),
    ),
  history: () =>
    finoraCall(
      { method: "GET", path: `${BASE}/history` },
      ok({
        rows: z.array(
          z.object({
            id: z.number().int(),
            product_id: z.number().int(),
            product_name: z.string().optional().default(""),
            old_price: z.number(),
            new_price: z.number(),
            source: z.string(),
            reason: z.string(),
            at: z.string(),
          }),
        ),
      }),
    ),
};
