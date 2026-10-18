import { z } from "zod";
import { finoraCall } from "./transport";
import { desktopBridge } from "@/services/bridge";

const totals = z.object({ assets: z.number(), liabilities: z.number(), net_assets: z.number() });
const issue = z.object({ key: z.string(), message: z.string(), amount: z.number() });
const source = z.object({
  key: z.string(),
  name: z.string(),
  type: z.enum(["asset", "liability"]),
  target: z.number(),
  current: z.number().nullable(),
  difference: z.number().nullable(),
  account_ids: z.array(z.number()),
  treasury_account_id: z.number().optional(),
  treasury_type: z.string().optional(),
});
const current = z.object({
  rows: z.array(source),
  registered: totals,
  ledger: totals.extend({ profit: z.number(), equity: z.number(), balanced: z.boolean() }),
  coverage_issues: z.array(issue),
  independent_branches: z.boolean(),
  generated_at: z.string(),
  basis_version: z.number(),
});
const summary = z.object({
  id: z.number(),
  name: z.string(),
  created_at: z.string(),
  created_by: z.string(),
  reason: z.string(),
  net_assets: z.number(),
  ledger_profit: z.number(),
  coverage_issues_count: z.number(),
});
const details = summary.extend({
  data: current.extend({
    measured: totals,
    treasury_counts: z.array(
      z.object({
        id: z.number(),
        name: z.string(),
        registered: z.number(),
        actual: z.number(),
        difference: z.number(),
        evidence: z.string(),
      }),
    ),
    ledger_cursor: z.number(),
    ledger_hash: z.string(),
  }),
});
const comparison = z.object({
  start: summary,
  end: summary,
  net_assets_change: z.number(),
  capital: z.number(),
  owner_drawings: z.number(),
  opening_adjustments: z.number(),
  other_equity: z.number(),
  accounting_profit: z.number(),
  derived_profit: z.number(),
  difference: z.number(),
  matched: z.boolean(),
  coverage_issues: z.array(issue),
  note: z.string(),
});
const envelope = <T extends z.ZodTypeAny>(schema: T) =>
  z.object({ success: z.literal(true), data: schema }).transform((value) => value.data);
const get = <T>(path: string, schema: z.ZodType<T>, query?: Record<string, string | number>) =>
  finoraCall({ method: "GET", path: `/api/finance/control/${path}`, query }, envelope(schema));
export type ControlSource = z.infer<typeof source>;
export type ControlSnapshot = z.infer<typeof summary>;
export const financialControl = {
  printSnapshot: (id: number) => desktopBridge().print.open({ kind: "financial_control_snapshot", id }),
  printComparison: (start: number, end: number) =>
    desktopBridge().print.open({ kind: "financial_control_comparison", start, end }),
  current: () => get("current", current),
  list: (page: number, pageSize: number) =>
    get(
      "snapshots",
      z.object({ items: z.array(summary), total: z.number(), page: z.number(), page_size: z.number() }),
      { page, page_size: pageSize },
    ),
  details: (id: number) => get(`snapshots/${id}`, details),
  compare: (start: number, end: number) => get("compare", comparison, { start, end }),
  measure: (
    body: {
      name: string;
      reason: string;
      treasury_counts: { id: number; actual: number; evidence: string }[];
    },
    key: string,
  ) =>
    finoraCall(
      {
        method: "POST",
        path: "/api/finance/commands",
        body: { ...body, operation: "control.measure", idempotency_key: key },
      },
      envelope(summary),
    ),
};
