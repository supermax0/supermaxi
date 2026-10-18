import { z } from "zod";

export const snapshotDatasets = [
  "products",
  "product-details",
  "purchases",
  "purchase-details",
  "purchase-products",
  "suppliers",
  "supplier-details",
  "supplier-products",
  "orders",
  "order-details",
  "order-lookups",
  "order-counts",
  "pos-products",
  "pos-bootstrap",
  "payment-accounts",
  "customers",
] as const;
export type SnapshotDataset = (typeof snapshotDatasets)[number];
export const snapshotManifestSchema = z
  .object({
    success: z.literal(true),
    version: z.literal(1),
    id: z.string().uuid(),
    tenant_slug: z.string(),
    user_id: z.number().int(),
    branch_id: z.number().int().nullable(),
    branch_scope: z.enum(["branch", "all", "shared"]),
    permissions: z.array(z.string()),
    started_at: z.number().int().nonnegative(),
    captured_at: z.number().int().nonnegative(),
    expires_at: z.number().int().positive(),
    datasets: z
      .array(
        z.object({
          name: z.enum(snapshotDatasets),
          total: z.number().int().min(0).max(50000),
          page_size: z.literal(100),
          meta: z.record(z.unknown()),
        }),
      )
      .max(snapshotDatasets.length),
  })
  .refine((v) => new Set(v.datasets.map((d) => d.name)).size === v.datasets.length, "مجموعات التنزيل مكررة");
export type SnapshotManifest = z.infer<typeof snapshotManifestSchema>;
export const snapshotPageSchema = z.object({
  success: z.literal(true),
  id: z.string().uuid(),
  dataset: z.enum(snapshotDatasets),
  cursor: z.number().int().nonnegative(),
  next_cursor: z.number().int().positive(),
  rows_json: z.string().max(8 * 1024 * 1024),
  digest: z.string().regex(/^[a-f0-9]{64}$/),
});
export const snapshotRowsSchema = z.array(z.object({ id: z.number().int() }).passthrough()).max(100);
export interface SnapshotStatus {
  capturedAt: number | null;
  downloaded: number;
  total: number;
  downloading: boolean;
  resumable: boolean;
  stale: boolean;
  datasets: Array<{ name: SnapshotDataset; total: number }>;
  error: string | null;
}
