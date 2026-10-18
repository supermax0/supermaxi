import { z } from "zod";
import { finoraCall } from "./transport";

/** Store dashboard — modules/store_analytics over /api/v1/desktop/store-analytics. Read only (view_financial). */
const BASE = "/api/v1/desktop/store-analytics";
const ok = <T extends z.ZodRawShape>(shape: T) => z.object({ success: z.literal(true), ...shape });
const pct = z.number().nullable();
const queryCount = z.object({ query: z.string(), count: z.number() });

const dashboardSchema = ok({
  days: z.number(),
  behaviour: z.object({
    sessions: z.number(),
    searches: z.number(),
    searches_no_results: z.number(),
    no_result_rate: pct,
    top_searches: z.array(queryCount),
    top_no_results: z.array(queryCount),
    product_views: z.number(),
    add_to_cart: z.number(),
    removed_from_cart: z.number(),
    checkout_started: z.number(),
    orders: z.number(),
    conversion_rate: pct,
    funnel: z.array(z.object({ step: z.string(), count: z.number() })),
  }),
  sales: z.object({
    orders: z.number(),
    orders_all: z.number(),
    revenue: z.number(),
    average_order_value: z.number(),
    units_per_order: z.number(),
    estimated_margin: z.number(),
    estimated_margin_pct: pct,
    cancel_rate: pct,
    return_rate: pct,
    top_products: z.array(z.object({ product_id: z.number(), name: z.string(), units: z.number() })),
  }),
  recommendations: z.object({
    sections: z.array(
      z.object({
        section: z.string(),
        views: z.number(),
        clicks: z.number(),
        ctr: pct,
        attributed_sales: z.number(),
        attributed_value: z.number(),
      }),
    ),
    attributed_value: z.number(),
    experiment: z
      .object({
        holdout_pct: z.number(),
        holdout: z.object({ sessions: z.number(), orders: z.number(), conversion_rate: pct }),
        exposed: z.object({ sessions: z.number(), orders: z.number(), conversion_rate: pct }),
        enough_data: z.boolean(),
        min_sessions_per_group: z.number(),
      })
      .nullable(),
  }),
  unmet_demand: z.object({
    viewed_out_of_stock: z.array(z.object({ product_id: z.number(), name: z.string(), views: z.number() })),
    availability_requests: z.array(
      z.object({ catalog_id: z.number(), title: z.string(), requests: z.number() }),
    ),
  }),
  vitals: z.array(
    z.object({
      page: z.string(),
      samples: z.number(),
      lcp_p75_ms: z.number().nullable(),
      cls_p75: z.number().nullable(),
      inp_p75_ms: z.number().nullable(),
      passes: z.object({
        lcp: z.boolean().nullable(),
        cls: z.boolean().nullable(),
        inp: z.boolean().nullable(),
      }),
    }),
  ),
  server: z.object({
    since: z.number(),
    rows: z.array(
      z.object({
        endpoint: z.string(),
        count: z.number(),
        p50_ms: z.number(),
        p95_ms: z.number(),
        max_ms: z.number(),
      }),
    ),
  }),
});
export type StoreDashboard = z.infer<typeof dashboardSchema>;

const settingsSchema = ok({ design_v2: z.boolean(), about_text: z.string(), returns_policy: z.string() });
export type StoreSettings = { design_v2: boolean; about_text: string; returns_policy: string };

export const storeAnalytics = {
  settings: () => finoraCall({ method: "GET", path: `${BASE}/settings` }, settingsSchema),
  saveSettings: (input: Partial<StoreSettings>) =>
    finoraCall({ method: "POST", path: `${BASE}/settings`, body: { ...input } }, settingsSchema),
  dashboard: (days: number) =>
    finoraCall({ method: "GET", path: `${BASE}?days=${days}`, timeoutMs: 60_000 }, dashboardSchema),
  setExperiment: (holdoutPct: number) =>
    finoraCall(
      { method: "POST", path: `${BASE}/experiment`, body: { holdout_pct: holdoutPct } },
      ok({ holdout_pct: z.number() }),
    ),
};
