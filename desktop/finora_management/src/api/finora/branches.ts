import { z } from "zod";
import { finoraCall } from "./transport";

/** Branches & warehouses — modules/desktop_api/branches.py over utils/branch_management. */
const BASE = "/api/v1/desktop/branches";

const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ ok: z.literal(true), ...shape });

const statsSchema = z.object({
  sales_total: z.number(),
  orders: z.number().int(),
  open_orders: z.number().int(),
  stock_value: z.number(),
  /** Sent and not yet settled — still the sender's property, at its original cost. */
  in_transit_value: z.number().default(0),
  /** null = the balance could not be computed; never shown as a partial number. */
  cash: z.number().nullable(),
  last_activity: z.string(),
});
export type BranchStats = z.infer<typeof statsSchema>;

export const branchSchema = z.object({
  id: z.number().int(),
  code: z.string(),
  name: z.string(),
  address: z.string(),
  phone: z.string(),
  is_active: z.boolean(),
  is_default: z.boolean(),
  created_at: z.string(),
  short_name: z.string(),
  branch_type: z.string(),
  branch_type_label: z.string(),
  governorate: z.string(),
  city: z.string(),
  email: z.string(),
  manager_name: z.string(),
  opened_on: z.string(),
  archived_at: z.string(),
  archive_reason: z.string(),
  stats: statsSchema.nullable(),
});
export type Branch = z.infer<typeof branchSchema>;

const multiBranchSchema = z.object({
  enabled: z.boolean(),
  explicit: z.boolean(),
  active_branches: z.number().int(),
});

const metaSchema = ok({
  multi_branch: multiBranchSchema,
  primary_branch_id: z.number().int().nullable(),
  can_manage: z.boolean(),
  can_report: z.boolean().default(false),
  types: z.array(z.object({ id: z.string(), label: z.string() })),
  current_branch_id: z.number().int().nullable(),
  transfer_policy: z.object({ approval_required: z.boolean() }).default({ approval_required: false }),
  scope: z.object({
    can_switch: z.boolean(),
    view_all: z.boolean(),
    /** shared-branch mode: records are not split by branch, every screen shows all of them */
    shared: z.boolean().optional().default(false),
    branches: z.array(
      z.object({ id: z.number().int(), name: z.string(), code: z.string(), is_default: z.boolean() }),
    ),
  }),
});
export type BranchesMeta = z.infer<typeof metaSchema>;

export interface BranchInput {
  code?: string;
  name?: string;
  branch_type?: string;
  governorate?: string;
  city?: string;
  address?: string;
  phone?: string;
  email?: string;
  manager_name?: string;
  opened_on?: string;
  is_default?: boolean;
}

const branchEnvelope = ok({ branch: branchSchema });

const personSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  role: z.string().nullable().optional(),
  home_branch_id: z.number().int().nullable(),
  home_branch: z.string(),
  extras: z.array(z.object({ branch_id: z.number().int(), name: z.string() })),
});
export type BranchPerson = z.infer<typeof personSchema>;
const peopleEnvelope = ok({ rows: z.array(personSchema) });

export interface ExpenseSplitInput {
  amount: number;
  rule: string;
  branch_ids: number[];
  weights?: Record<string, number>;
  from?: string;
  to?: string;
}

export type DistributionItem =
  | {
      type: "stock";
      product_id: number;
      variant_color?: string | null;
      quantity: number;
      from_branch_id: number;
      to_branch_id: number;
    }
  | { type: "cash"; from_account_id: number; to_account_id: number; amount: number }
  | { type: "staff"; employee_id: number; branch_id: number; mode: "extra" | "move" };

const distributionItem = z
  .object({
    type: z.enum(["stock", "cash", "staff"]),
    state: z.string(),
    error: z.string().nullable().optional(),
    ref: z.string().nullable().optional(),
  })
  .passthrough();
const distributionSession = z.object({
  id: z.number().int(),
  number: z.string(),
  title: z.string(),
  status: z.enum(["draft", "ready", "executing", "completed", "failed", "cancelled"]),
  created_at: z.string(),
  finished_at: z.string(),
  done: z.number().int(),
  failed: z.number().int(),
  total: z.number().int(),
  backup_path: z.string().default(""),
  items: z.array(distributionItem),
});
export type DistributionSession = z.infer<typeof distributionSession>;
const distributionPreview = z.object({
  items: z.array(
    distributionItem
      .extend({ index: z.number().int(), verdict: z.string(), reason: z.string() })
      .passthrough(),
  ),
  summary: z.object({
    stock_units: z.number(),
    stock_value: z.number(),
    cash: z.number(),
    staff: z.number(),
    blocked: z.number(),
    items: z.number(),
  }),
  can_execute: z.boolean(),
});
export type DistributionPreview = z.infer<typeof distributionPreview>;

export const branches = {
  meta: () => finoraCall({ method: "GET", path: `${BASE}/meta` }, metaSchema),
  list: (archived: boolean) =>
    finoraCall(
      { method: "GET", path: BASE, query: { archived: archived ? "1" : "0" } },
      ok({
        rows: z.array(branchSchema),
        multi_branch: multiBranchSchema,
        pending_transfers: z
          .object({ stock: z.number().int(), cash: z.number().int(), cash_amount: z.number() })
          .optional(),
      }),
    ),
  detail: (id: number) =>
    finoraCall(
      { method: "GET", path: `${BASE}/${id}` },
      ok({ branch: branchSchema, blockers: z.array(z.string()) }),
    ),
  create: (input: BranchInput) =>
    finoraCall({ method: "POST", path: BASE, body: { ...input } }, branchEnvelope),
  update: (id: number, input: BranchInput) =>
    finoraCall({ method: "POST", path: `${BASE}/${id}/update`, body: { ...input } }, branchEnvelope),
  archive: (id: number, input: { reason?: string; restore?: boolean }) =>
    finoraCall({ method: "POST", path: `${BASE}/${id}/archive`, body: { ...input } }, branchEnvelope),
  setFeature: (enabled: boolean) =>
    finoraCall(
      { method: "POST", path: `${BASE}/feature`, body: { enabled } },
      ok({ multi_branch: multiBranchSchema }),
    ),
  setTransferPolicy: (approvalRequired: boolean) =>
    finoraCall(
      { method: "POST", path: `${BASE}/transfer-policy`, body: { approval_required: approvalRequired } },
      ok({ transfer_policy: z.object({ approval_required: z.boolean() }) }),
    ),
  /** Quantity of one product in every active branch (admin, or when the company sells from all branches). */
  availability: (productId: number) =>
    finoraCall(
      { method: "GET", path: `${BASE}/availability`, query: { product_id: String(productId) } },
      ok({
        rows: z.array(
          z.object({
            id: z.number().int(),
            name: z.string(),
            code: z.string(),
            quantity: z.number(),
            is_current: z.boolean(),
          }),
        ),
        total: z.number(),
      }),
    ),
  expenseAssignments: (from: string, to: string) =>
    finoraCall(
      { method: "GET", path: `${BASE}/expense-allocation/assignments`, query: { from, to } },
      ok({
        rows: z.record(
          z.object({
            kind: z.enum(["central", "shared"]),
            rule: z.string().nullable(),
            lines: z.array(z.object({ branch_id: z.number().int(), amount: z.number() })),
          }),
        ),
      }),
    ),
  /** What a rule WOULD do; stores nothing. */
  previewExpenseSplit: (input: ExpenseSplitInput) =>
    finoraCall(
      { method: "POST", path: `${BASE}/expense-allocation/preview`, body: { ...input } },
      ok({
        amount: z.number(),
        lines: z.array(
          z.object({
            branch_id: z.number().int(),
            branch: z.string(),
            weight: z.number().nullable(),
            amount: z.number(),
          }),
        ),
      }),
    ),
  allocateExpense: (
    expenseId: number,
    input: {
      kind: "branch" | "central" | "shared";
      rule?: string;
      branch_ids?: number[];
      weights?: Record<string, number>;
      from?: string;
      to?: string;
    },
  ) =>
    finoraCall(
      { method: "POST", path: `${BASE}/expense-allocation/${expenseId}`, body: { ...input } },
      ok({ expense_id: z.number().int(), kind: z.string() }).passthrough(),
    ),
  /** Attribution overlay only: branch totals + central + unassigned always add up to company_total. */
  expenseReport: (from: string, to: string) =>
    finoraCall(
      { method: "GET", path: `${BASE}/expense-allocation/report`, query: { from, to } },
      ok({
        from: z.string(),
        to: z.string(),
        branches: z.array(z.object({ branch_id: z.number().int(), branch: z.string(), amount: z.number() })),
        central: z.number(),
        unassigned: z.number(),
        company_total: z.number(),
      }),
    ),
  distributionList: () =>
    finoraCall(
      { method: "GET", path: `${BASE}/distribution` },
      ok({
        eligibility: z.object({ eligible: z.boolean(), reasons: z.array(z.string()) }),
        rows: z.array(distributionSession),
      }),
    ),
  distributionCreate: (title: string, items: DistributionItem[]) =>
    finoraCall(
      { method: "POST", path: `${BASE}/distribution`, body: { title, items } },
      ok({ session: distributionSession }),
    ),
  distributionDetail: (id: number) =>
    finoraCall(
      { method: "GET", path: `${BASE}/distribution/${id}` },
      ok({ session: distributionSession, preview: distributionPreview }),
    ),
  distributionAct: (id: number, action: "approve" | "execute" | "cancel") =>
    finoraCall(
      { method: "POST", path: `${BASE}/distribution/${id}/${action}`, body: {}, timeoutMs: 60_000 },
      ok({ session: distributionSession }),
    ),
  /** Comparison of branches for a period; unsourced figures (profit) are deliberately absent. */
  report: (from: string, to: string) =>
    finoraCall(
      { method: "GET", path: `${BASE}/report`, query: { from, to } },
      ok({
        from: z.string(),
        to: z.string(),
        branches: z.array(
          z.object({
            branch_id: z.number().int(),
            branch: z.string(),
            code: z.string(),
            sales: z.number(),
            orders: z.number(),
            average_invoice: z.number(),
            canceled: z.number(),
            returned: z.number(),
            returns_value: z.number(),
            expenses: z.number(),
            stock_value: z.number(),
            in_transit_value: z.number(),
            cash: z.number().nullable(),
          }),
        ),
        totals: z.record(z.number().nullable()),
        central_expenses: z.number(),
        unassigned_expenses: z.number(),
        notes: z.array(z.string()),
      }),
    ),
  people: () => finoraCall({ method: "GET", path: `${BASE}/people` }, peopleEnvelope),
  /** extra = may also work in the branch; move = changes the home branch (history is kept). */
  assignPerson: (employeeId: number, input: { branch_id: number; mode: "extra" | "move"; note?: string }) =>
    finoraCall(
      { method: "POST", path: `${BASE}/people/${employeeId}/assign`, body: { ...input } },
      peopleEnvelope.passthrough(),
    ),
  unassignPerson: (employeeId: number, branchId: number) =>
    finoraCall(
      { method: "POST", path: `${BASE}/people/${employeeId}/unassign`, body: { branch_id: branchId } },
      peopleEnvelope,
    ),
  /** Changes the VIEW scope only; creating operations still needs one real branch (enforced server-side). */
  switchScope: (target: { branch_id: number } | { view_all: true }) =>
    finoraCall(
      { method: "POST", path: `${BASE}/switch`, body: { ...target } },
      z.object({ ok: z.literal(true) }).passthrough(),
    ),
};
