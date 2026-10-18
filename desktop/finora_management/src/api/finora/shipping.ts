import { z } from "zod";
import { finoraCall } from "./transport";

/** Shipping & Logistics Center — modules/desktop_api/shipping_center.py over FINORA's own manifests. */
const BASE = "/api/v1/desktop/shipping-center";

export const ROW_STATUSES = ["واصل", "راجع", "مؤجل", "مشكلة"] as const;
export type RowStatus = (typeof ROW_STATUSES)[number];

const amount = z.object({ count: z.number().int(), amount: z.number() });
const statsSchema = z.object({
  total: amount,
  transit: amount,
  delivered_unsettled: amount,
  due: amount,
  returned: amount,
});
export type BucketStats = z.infer<typeof statsSchema>;

export const orderRowSchema = z.object({
  id: z.number().int(),
  customer_name: z.string(),
  customer_phone: z.string(),
  customer_city: z.string(),
  customer_address: z.string(),
  total: z.number(),
  paid_amount: z.number(),
  remaining: z.number(),
  status: z.string(),
  shipping_status: z.string(),
  payment_status: z.string(),
  shipping_company_id: z.number().int().nullable(),
  shipping_company: z.string(),
  delivery_agent_id: z.number().int().nullable(),
  delivery_agent: z.string(),
  waybills: z.array(z.string()),
  fee: z.number(),
  fee_due: z.number().default(0),
  created_at: z.string(),
});
export type ShipOrder = z.infer<typeof orderRowSchema>;

const manifestSummarySchema = z.object({
  id: z.number().int(),
  number: z.string(),
  kind: z.enum(["settlement", "agent", "handover"]),
  carrier_id: z.number().int().nullable(),
  carrier: z.string(),
  agent_id: z.number().int().nullable().default(null),
  agent: z.string(),
  settlement_state: z.enum(["draft", "full", "partial", "executed"]).default("draft"),
  orders_count: z.number().int(),
  total_amount: z.number(),
  executed: z.boolean(),
  created_at: z.string(),
  created_by: z.string(),
  reference: z.string(),
  breakdown: z.record(z.unknown()),
});
export type ManifestSummary = z.infer<typeof manifestSummarySchema>;

const issueSchema = z.object({
  severity: z.enum(["error", "warning"]),
  code: z.string(),
  order_id: z.number().int().nullable(),
  message: z.string(),
});
export type ManifestIssue = z.infer<typeof issueSchema>;

const totalsSchema = z.object({
  delivered: z.object({ count: z.number().int(), amount: z.number(), fee: z.number() }),
  returned: z.object({ count: z.number().int(), amount: z.number(), fee: z.number().default(0) }),
  postponed: amount,
  problem: amount,
  unclassified: amount,
});

export const manifestSchema = manifestSummarySchema.extend({
  meta: z.record(z.unknown()),
  selections: z.record(z.string()),
  rows: z.array(orderRowSchema.extend({ selection: z.string(), allocated: z.number().optional() })),
  issues: z.array(issueSchema),
  blocking: z.array(issueSchema),
  totals: totalsSchema,
  expected_net: z.number(),
  ready: z.boolean(),
  return_fee_each: z.number().default(0),
});
export type Manifest = z.infer<typeof manifestSchema>;
export type ManifestRow = Manifest["rows"][number];

const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ ok: z.literal(true), ...shape });

const metaSchema = ok({
  carriers: z.array(
    z.object({ id: z.number().int(), name: z.string(), phone: z.string(), price: z.number() }),
  ),
  agents: z.array(
    z.object({
      id: z.number().int(),
      name: z.string(),
      phone: z.string(),
      carrier_id: z.number().int().nullable(),
    }),
  ),
  treasury_accounts: z.array(z.object({ id: z.number().int(), name: z.string(), is_default: z.boolean() })),
  can_approve: z.boolean(),
  can_manage: z.boolean(),
});
export type ShippingMeta = z.infer<typeof metaSchema>;

const overviewSchema = ok({
  cards: z.object({
    in_transit: z.object({ count: z.number().int() }),
    delivered_unsettled: amount,
    carriers_due: amount,
    agents_due: amount,
    returns: z.object({ count: z.number().int() }),
    open_manifests: z.object({ count: z.number().int(), flagged: z.number().int() }),
  }),
});
export type ShippingOverview = z.infer<typeof overviewSchema>;

const carrierRowSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  phone: z.string(),
  price: z.number(),
  notes: z.string(),
  opening_balance: z.number(),
  stats: statsSchema,
  due: z.number(),
  open_manifests: z.number().int(),
});
export type CarrierRow = z.infer<typeof carrierRowSchema>;

const agentRowSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  phone: z.string(),
  active: z.boolean(),
  carrier: z.string(),
  has_portal: z.boolean(),
  stats: statsSchema,
});
export type AgentRow = z.infer<typeof agentRowSchema>;

const carrierDetailsSchema = ok({
  carrier: z.object({
    id: z.number().int(),
    name: z.string(),
    phone: z.string(),
    price: z.number(),
    notes: z.string(),
  }),
  stats: statsSchema,
  received_total: z.number(),
  balance: z.number().default(0),
  manifests: z.array(manifestSummarySchema),
  statement: z.array(
    z.object({
      id: z.number().int(),
      date: z.string(),
      invoice_id: z.number().int().nullable(),
      action: z.string(),
      amount: z.number(),
      note: z.string(),
    }),
  ),
});
export type CarrierDetails = z.infer<typeof carrierDetailsSchema>;

const agentDetailsSchema = ok({
  agent: z.object({
    id: z.number().int(),
    name: z.string(),
    phone: z.string(),
    active: z.boolean(),
    carrier: z.string(),
    has_portal: z.boolean(),
  }),
  stats: statsSchema,
  custody: z
    .object({
      claimed_count: z.number().int(),
      claimed_amount: z.number(),
      settled_outstanding: z.number(),
      received_total: z.number(),
      in_custody: z.number(),
    })
    .optional(),
  manifests: z.array(manifestSummarySchema),
});
export type AgentDetails = z.infer<typeof agentDetailsSchema>;

export type OrderBucket = "all" | "transit" | "delivered_unsettled" | "due" | "returned";
const ordersPageSchema = ok({
  rows: z.array(orderRowSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
});
export type ShipOrdersPage = z.infer<typeof ordersPageSchema>;

export interface ManifestFilters {
  state: "all" | "open" | "executed";
  kind: "" | "settlement" | "handover" | "agent";
  search: string;
  carrierId?: number | null;
}

const manifestEnvelope = ok({ manifest: manifestSchema });

const statementSchema = ok({
  lines: z.array(
    z.object({
      date: z.string(),
      manifest_id: z.number().int(),
      manifest_number: z.string(),
      label: z.string(),
      debit: z.number(),
      credit: z.number(),
      balance: z.number(),
    }),
  ),
  debit: z.number(),
  credit: z.number(),
  balance: z.number(),
});
export type PartyStatement = z.infer<typeof statementSchema>;

const receiptSchema = z.object({
  id: z.number().int(),
  number: z.string(),
  party_type: z.enum(["carrier", "agent"]),
  party_id: z.number().int(),
  party_name: z.string(),
  amount: z.number(),
  payment_method: z.string(),
  treasury_account: z.string(),
  date: z.string(),
  reference: z.string(),
  notes: z.string(),
  status: z.string(),
  balance_before: z.number(),
  balance_after: z.number(),
  created_by: z.string(),
  allocations: z.array(z.object({ order_id: z.number().int(), label: z.string(), amount: z.number() })),
});
export type ShippingReceipt = z.infer<typeof receiptSchema>;

export const CYCLES = { daily: "يومي", weekly: "أسبوعي", manifest: "حسب الكشف" } as const;
const settingsSchema = z.object({
  carrier_id: z.number().int(),
  price: z.number(),
  return_fee: z.number(),
  settlement_cycle: z.enum(["daily", "weekly", "manifest"]),
  payment_method: z.enum(["cash", "bank"]),
  treasury_account_id: z.number().int().nullable(),
  notes: z.string(),
  updated_by: z.string(),
  updated_at: z.string(),
});
export type CarrierSettings = z.infer<typeof settingsSchema>;

export type ReturnState = "awaiting" | "received" | "closed";
const returnItemSchema = z.object({
  item_id: z.number().int(),
  product_id: z.number().int(),
  name: z.string(),
  variant: z.string(),
  quantity: z.number().int(),
});
export type ReturnItem = z.infer<typeof returnItemSchema>;
const returnSchema = z.object({
  id: z.number().int(),
  order_id: z.number().int(),
  state: z.enum(["awaiting", "received", "closed"]),
  manifest_id: z.number().int().nullable(),
  manifest_number: z.string(),
  party_type: z.string(),
  party_id: z.number().int().nullable(),
  party_name: z.string(),
  order_amount: z.number(),
  customer_name: z.string(),
  customer_city: z.string(),
  order_status: z.string(),
  waybills: z.array(z.string()),
  reported_at: z.string(),
  received_at: z.string(),
  received_by: z.string(),
  closed_at: z.string(),
  closed_by: z.string(),
  branch_id: z.number().int().nullable(),
  packaging_ok: z.boolean().nullable(),
  inspection: z.array(
    returnItemSchema.partial().extend({ sellable: z.number().optional(), damaged: z.number().optional() }),
  ),
  writeoffs: z.array(z.string()),
  note: z.string(),
  items: z.array(returnItemSchema).optional(),
  branches: z.array(z.object({ id: z.number().int(), name: z.string() })).optional(),
});
export type ShippingReturn = z.infer<typeof returnSchema>;

const heldOrderSchema = orderRowSchema.extend({ days_out: z.number().int(), in_manifest: z.string() });
export type HeldOrder = z.infer<typeof heldOrderSchema>;
const overdueSchema = ok({
  days: z.number().int(),
  parcels: z.array(heldOrderSchema),
  returns: z.array(
    z.object({
      id: z.number().int(),
      order_id: z.number().int(),
      state: z.string(),
      party_name: z.string(),
      manifest_number: z.string(),
      order_amount: z.number(),
      days: z.number().int(),
    }),
  ),
  manifests: z.array(manifestSummarySchema.extend({ days: z.number().int() })),
  counts: z.object({ parcels: z.number().int(), returns: z.number().int(), manifests: z.number().int() }),
  amount: z.number(),
});
export type ShippingOverdue = z.infer<typeof overdueSchema>;

export const shipping = {
  meta: () => finoraCall({ method: "GET", path: `${BASE}/meta` }, metaSchema),
  overview: () => finoraCall({ method: "GET", path: `${BASE}/overview` }, overviewSchema),
  carriers: () =>
    finoraCall({ method: "GET", path: `${BASE}/carriers` }, ok({ rows: z.array(carrierRowSchema) })),
  carrier: (id: number) =>
    finoraCall({ method: "GET", path: `${BASE}/carriers/${id}` }, carrierDetailsSchema),
  agents: () => finoraCall({ method: "GET", path: `${BASE}/agents` }, ok({ rows: z.array(agentRowSchema) })),
  /** Same-branch duplicate agent records (general admin only; 403 for everyone else). */
  duplicateAgents: () =>
    finoraCall(
      { method: "GET", path: `${BASE}/agents/duplicates` },
      ok({
        rows: z.array(
          z.object({
            branch_id: z.number().int().nullable(),
            name: z.string(),
            phone: z.string(),
            primary_id: z.number().int(),
            can_merge: z.boolean(),
            duplicates: z.array(
              z.object({
                id: z.number().int(),
                invoices: z.number().int(),
                has_login: z.boolean(),
                blocker: z.string(),
              }),
            ),
          }),
        ),
      }),
    ),
  mergeAgents: (primaryId: number, duplicateIds: number[]) =>
    finoraCall(
      {
        method: "POST",
        path: `${BASE}/agents/merge`,
        body: { primary_id: primaryId, duplicate_ids: duplicateIds },
      },
      ok({ primary_id: z.number().int(), invoices_moved: z.number().int(), backup: z.string() }),
    ),
  agent: (id: number) => finoraCall({ method: "GET", path: `${BASE}/agents/${id}` }, agentDetailsSchema),
  orders(owner: "carriers" | "agents", id: number, bucket: OrderBucket, search: string, page: number) {
    return finoraCall(
      {
        method: "GET",
        path: `${BASE}/${owner}/${id}/orders`,
        query: { bucket, search: search.trim(), page, page_size: 25 },
      },
      ordersPageSchema,
    );
  },
  lookup: (codes: string[]) =>
    finoraCall(
      { method: "POST", path: `${BASE}/lookup`, body: { codes } },
      ok({ found: z.array(orderRowSchema.extend({ code: z.string() })), missing: z.array(z.string()) }),
    ),
  manifests: (f: ManifestFilters) =>
    finoraCall(
      {
        method: "GET",
        path: `${BASE}/manifests`,
        query: { state: f.state, kind: f.kind, search: f.search.trim(), carrier_id: f.carrierId ?? "" },
      },
      ok({ rows: z.array(manifestSummarySchema) }),
    ),
  manifest: (id: number) => finoraCall({ method: "GET", path: `${BASE}/manifests/${id}` }, manifestEnvelope),
  createSettlement: (input: {
    carrier_id?: number;
    agent_id?: number;
    from_portal?: boolean;
    reference: string;
    date: string;
  }) => finoraCall({ method: "POST", path: `${BASE}/manifests`, body: { ...input } }, manifestEnvelope),
  addRows: (id: number, codes: string[]) =>
    finoraCall(
      { method: "POST", path: `${BASE}/manifests/${id}/rows`, body: { codes }, timeoutMs: 60_000 },
      ok({
        manifest: manifestSchema,
        added: z.array(z.number().int()),
        duplicates: z.array(z.string()),
        missing: z.array(z.string()),
      }),
    ),
  removeRow: (id: number, orderId: number) =>
    finoraCall({ method: "POST", path: `${BASE}/manifests/${id}/rows/${orderId}/remove` }, manifestEnvelope),
  saveSelections: (id: number, selections: Record<string, RowStatus | "">) =>
    finoraCall(
      { method: "POST", path: `${BASE}/manifests/${id}/selections`, body: { selections } },
      manifestEnvelope,
    ),
  approve: (
    id: number,
    input: {
      received_amount: number;
      treasury_account_id: number | null;
      payment_method?: "cash" | "bank";
      allocations?: Record<string, number>;
    },
  ) =>
    finoraCall(
      {
        method: "POST",
        path: `${BASE}/manifests/${id}/approve`,
        body: { ...input, treasury_account_id: input.treasury_account_id ?? "" },
        timeoutMs: 60_000,
      },
      ok({ manifest: manifestSchema, result: z.record(z.unknown()) }),
    ),
  statement: (owner: "carriers" | "agents", id: number) =>
    finoraCall({ method: "GET", path: `${BASE}/${owner}/${id}/statement` }, statementSchema),
  receipts: (filter: { party_type?: "carrier" | "agent"; party_id?: number; search?: string } = {}) =>
    finoraCall(
      {
        method: "GET",
        path: `${BASE}/receipts`,
        query: {
          party_type: filter.party_type ?? "",
          party_id: filter.party_id ?? "",
          search: filter.search ?? "",
        },
      },
      ok({ rows: z.array(receiptSchema) }),
    ),
  settings: (carrierId: number) =>
    finoraCall(
      { method: "GET", path: `${BASE}/carriers/${carrierId}/settings` },
      ok({ settings: settingsSchema }),
    ),
  saveSettings: (
    carrierId: number,
    input: Omit<CarrierSettings, "carrier_id" | "updated_by" | "updated_at">,
  ) =>
    finoraCall(
      { method: "POST", path: `${BASE}/carriers/${carrierId}/settings`, body: { ...input } },
      ok({ settings: settingsSchema }),
    ),
  returns: (state: "open" | ReturnState | "all", search: string) =>
    finoraCall(
      { method: "GET", path: `${BASE}/returns`, query: { state, search: search.trim() } },
      ok({
        rows: z.array(returnSchema),
        counts: z.object({
          awaiting: z.number().int(),
          received: z.number().int(),
          closed: z.number().int(),
        }),
      }),
    ),
  returnDetails: (id: number) =>
    finoraCall(
      { method: "GET", path: `${BASE}/returns/${id}` },
      ok({ item: returnSchema, can_writeoff: z.boolean() }),
    ),
  receiveReturn: (input: { code?: string; return_id?: number }) =>
    finoraCall(
      { method: "POST", path: `${BASE}/returns/receive`, body: { ...input } },
      ok({ item: returnSchema }),
    ),
  closeReturn: (
    id: number,
    input: {
      branch_id: number;
      packaging_ok: boolean;
      note: string;
      lines: Array<{ item_id: number; damaged: number }>;
    },
  ) =>
    finoraCall(
      { method: "POST", path: `${BASE}/returns/${id}/close`, body: { ...input }, timeoutMs: 60_000 },
      ok({ item: returnSchema }),
    ),
  agentPortal: (agentId: number) =>
    finoraCall(
      { method: "GET", path: `${BASE}/agents/${agentId}/portal` },
      ok({
        count: z.number().int(),
        counts: z.record(z.number()),
        amount: z.number(),
        can_approve: z.boolean(),
      }),
    ),
  missing: (manifestId: number) =>
    finoraCall(
      { method: "GET", path: `${BASE}/manifests/${manifestId}/missing` },
      ok({ rows: z.array(heldOrderSchema), total: z.number().int(), amount: z.number() }),
    ),
  overdue: (days: number) =>
    finoraCall({ method: "GET", path: `${BASE}/overdue`, query: { days } }, overdueSchema),
  agentReport: (agentId: number, orderIds: number[]) =>
    finoraCall(
      { method: "POST", path: `${BASE}/agent-report`, body: { agent_id: agentId, order_ids: orderIds } },
      ok({
        report_id: z.number().int(),
        report_number: z.string(),
        already_exists: z.boolean(),
        message: z.string(),
      }),
    ),
  handover: (carrierId: number, orderIds: number[]) =>
    finoraCall(
      { method: "POST", path: `${BASE}/handover`, body: { carrier_id: carrierId, order_ids: orderIds } },
      ok({ report_id: z.number().int(), report_number: z.string(), message: z.string() }),
    ),
};
