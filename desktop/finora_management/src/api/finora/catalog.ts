import { z } from "zod";
import { finoraCall, finoraForm } from "./transport";

/** Master catalogue (Smart Commerce V2) — modules/catalog over /api/v1/desktop/catalog. Never stock or prices. */
const BASE = "/api/v1/desktop/catalog";
const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ success: z.literal(true), ...shape });

export const VERIFICATION = {
  pending: "بانتظار البيانات",
  gathering: "جمع البيانات",
  matched: "مطابق",
  needs_review: "يحتاج مراجعة",
  verified: "موثّق",
  published: "منشور",
  failed: "فشل",
} as const;
export type Verification = keyof typeof VERIFICATION;

const entrySchema = z.object({
  id: z.number().int(),
  canonical_name: z.string(),
  brand: z.string(),
  model_number: z.string(),
  regional_version: z.string(),
  category: z.string(),
  description: z.string(),
  attributes: z.record(z.string()),
  verification_status: z.enum([
    "pending",
    "gathering",
    "matched",
    "needs_review",
    "verified",
    "published",
    "failed",
  ]),
  field_sources: z.record(z.object({ source: z.string(), confidence: z.number() })).default({}),
  barcodes: z.array(z.string()),
  media: z.array(
    z.object({
      id: z.number().int(),
      url: z.string(),
      role: z.string(),
      rights: z.string(),
      verified: z.boolean(),
    }),
  ),
  listing: z
    .object({
      is_published: z.boolean(),
      fulfillment_policy: z.string(),
      inventory_product_id: z.number().int().nullable(),
      is_featured: z.boolean(),
    })
    .nullable(),
});
export type CatalogEntry = z.infer<typeof entrySchema>;
const entryEnvelope = ok({ entry: entrySchema });

export interface CatalogEntryInput {
  canonical_name: string;
  brand: string;
  model_number: string;
  regional_version?: string;
  category?: string;
  description?: string;
  attributes?: Record<string, string>;
  barcodes?: string[];
  verification_status: Verification;
  media?: { url: string; usage_rights?: string }[];
}

const rowSchema = z.object({
  id: z.number().int(),
  row_no: z.number().int(),
  status: z.enum(["new", "matched", "linked", "duplicate", "needs_review", "invalid"]),
  data: z.record(z.unknown()),
  issues: z.array(z.string()),
  match_entry_id: z.number().int().nullable(),
  match_product_id: z.number().int().nullable(),
  applied_entry_id: z.number().int().nullable(),
});
export type ImportRow = z.infer<typeof rowSchema>;
const batchSchema = z.object({
  id: z.number().int(),
  filename: z.string(),
  status: z.string(),
  counts: z.record(z.number()),
  rows: z.array(rowSchema),
});
export type ImportBatch = z.infer<typeof batchSchema>;

export type CatalogFile = {
  name: string;
  type:
    | "text/csv"
    | "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    | "image/png"
    | "image/jpeg"
    | "image/webp";
  data: Uint8Array;
};

export const catalog = {
  settings: () =>
    finoraCall(
      { method: "GET", path: `${BASE}/settings` },
      ok({ catalog_layer: z.boolean(), pos_catalog_search: z.boolean() }),
    ),
  saveSettings: (input: { catalog_layer?: boolean; pos_catalog_search?: boolean }) =>
    finoraCall(
      { method: "POST", path: `${BASE}/settings`, body: { ...input } },
      ok({ catalog_layer: z.boolean(), pos_catalog_search: z.boolean() }),
    ),
  list: (q: string, page = 1) =>
    finoraCall(
      { method: "GET", path: `${BASE}/entries`, query: { q, page } },
      ok({ rows: z.array(entrySchema), total: z.number().int(), page: z.number().int() }),
    ),
  get: (id: number) => finoraCall({ method: "GET", path: `${BASE}/entries/${id}` }, entryEnvelope),
  save: (id: number | null, input: CatalogEntryInput) =>
    finoraCall(
      { method: "POST", path: id ? `${BASE}/entries/${id}` : `${BASE}/entries`, body: { ...input } },
      entryEnvelope,
    ),
  listing: (id: number, input: { publish: boolean; policy?: "request" | "stock_only"; featured?: boolean }) =>
    finoraCall({ method: "POST", path: `${BASE}/entries/${id}/listing`, body: { ...input } }, entryEnvelope),
  activate: (id: number, salePrice: number, posVisible: boolean) =>
    finoraCall(
      {
        method: "POST",
        path: `${BASE}/entries/${id}/activate`,
        body: { sale_price: salePrice, pos_visible: posVisible },
      },
      ok({ product_id: z.number().int() }),
    ),
  lookup: (q: string) =>
    finoraCall(
      { method: "GET", path: `${BASE}/lookup`, query: { q } },
      ok({
        query: z.string(),
        catalog: z.array(entrySchema),
        inventory: z
          .object({ id: z.number().int(), name: z.string(), sku: z.string(), barcode: z.string() })
          .nullable(),
        candidates: z.array(z.record(z.unknown())),
      }),
    ),
  importFile: (file: CatalogFile) =>
    finoraForm(
      { path: `${BASE}/imports`, fields: [], file: { field: "file", ...file }, timeoutMs: 60_000 },
      ok({ batch: batchSchema }),
    ),
  applyImport: (batchId: number, includeReview: boolean) =>
    finoraCall(
      {
        method: "POST",
        path: `${BASE}/imports/${batchId}/apply`,
        body: { include_review: includeReview },
        timeoutMs: 60_000,
      },
      ok({
        result: z.object({
          created: z.number().int(),
          updated: z.number().int(),
          linked: z.number().int(),
          skipped: z.number().int(),
        }),
      }),
    ),
  uploadImage: (id: number, file: CatalogFile, role = "") =>
    finoraForm(
      {
        path: `${BASE}/entries/${id}/media`,
        fields: [
          ["role", role],
          ["rights", "own_photo"],
        ],
        file: { field: "file", ...file },
      },
      entryEnvelope,
    ),
  mediaAction: (id: number, mediaId: number, action: "verify" | "unverify" | "remove") =>
    finoraCall(
      { method: "POST", path: `${BASE}/entries/${id}/media/${mediaId}/${action}`, body: {} },
      entryEnvelope,
    ),
  requests: () =>
    finoraCall(
      { method: "GET", path: `${BASE}/requests` },
      ok({
        rows: z.array(
          z.object({
            id: z.number().int(),
            product: z.string(),
            catalog_product_id: z.number().int(),
            customer_name: z.string(),
            phone: z.string(),
            city: z.string(),
            note: z.string(),
            status: z.string(),
            created_at: z.string(),
          }),
        ),
      }),
    ),
};
