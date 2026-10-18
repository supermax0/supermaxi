import { z } from "zod";
import { finoraCall } from "./transport";

/** Store recommendations — modules/recommendations over /api/v1/desktop/recommendations (manage_inventory).
 *  Relations confirmed by staff (accessory / compatible / upgrade / service) and bundles; the store never guesses
 *  compatibility, so only a «verified» relation is shown to shoppers. */
const BASE = "/api/v1/desktop/recommendations";
const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ success: z.literal(true), ...shape });

export const RELATION_TYPES = ["accessory", "compatible", "upgrade", "service"] as const;
export type RelationType = (typeof RELATION_TYPES)[number];

const relationSchema = z.object({
  id: z.number().int(),
  source_product_id: z.number().int(),
  source_name: z.string(),
  target_product_id: z.number().int(),
  target_name: z.string(),
  relation_type: z.enum(RELATION_TYPES),
  compatibility_note: z.string(),
  priority: z.number(),
  verified: z.boolean(),
});
export type ProductRelation = z.infer<typeof relationSchema>;
export interface RelationInput {
  source_product_id: number;
  target_product_id: number;
  relation_type: RelationType;
  compatibility_note: string;
  priority: number;
  verified: boolean;
}

const bundleSchema = z.object({
  id: z.number().int(),
  title: z.string(),
  description: z.string(),
  product_ids: z.array(z.number().int()),
  active: z.boolean(),
  products: z.array(z.object({ id: z.number().int(), name: z.string() })),
});
export type Bundle = z.infer<typeof bundleSchema>;
export interface BundleInput {
  title: string;
  description: string;
  product_ids: number[];
  active: boolean;
}

const previewSchema = ok({
  accessories: z.array(
    z.object({ id: z.number().int(), note: z.string().nullable().optional() }).passthrough(),
  ),
  bought_together: z.array(z.number().int()),
  upgrades: z.array(
    z.object({ id: z.number().int(), benefits: z.array(z.string()).optional() }).passthrough(),
  ),
  similar: z.array(z.number().int()),
  names: z.record(z.string()),
});
export type RecommendationPreview = z.infer<typeof previewSchema>;

export const recommendations = {
  relations: (productId?: number) =>
    finoraCall(
      {
        method: "GET",
        path: `${BASE}/relations`,
        query: productId ? { product_id: String(productId) } : undefined,
      },
      ok({ rows: z.array(relationSchema) }),
    ),
  saveRelation: (input: RelationInput) =>
    finoraCall(
      { method: "POST", path: `${BASE}/relations`, body: { ...input } },
      ok({ relation: relationSchema }),
    ),
  deleteRelation: (id: number) =>
    finoraCall({ method: "POST", path: `${BASE}/relations/${id}/delete`, body: {} }, ok({})),
  bundles: () => finoraCall({ method: "GET", path: `${BASE}/bundles` }, ok({ rows: z.array(bundleSchema) })),
  saveBundle: (id: number | null, input: BundleInput) =>
    finoraCall(
      { method: "POST", path: id ? `${BASE}/bundles/${id}` : `${BASE}/bundles`, body: { ...input } },
      ok({ bundle: bundleSchema }),
    ),
  preview: (productId: number) =>
    finoraCall({ method: "GET", path: `${BASE}/preview/${productId}`, timeoutMs: 30_000 }, previewSchema),
};
