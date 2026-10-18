/** Products — routes/inventory.py (same branch scope and quantities as the inventory page). */
import { z } from "zod";
import { MEDIA_SCHEME } from "@shared/ipc";
import { desktopBridge } from "@/services/bridge";
import { finoraCall, finoraForm } from "./transport";

export const STOCK_STATES = ["available", "low", "out"] as const;
export type StockState = (typeof STOCK_STATES)[number];

export const productRowSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  sku: z.string(),
  barcode: z.string(),
  category: z.string(),
  brand: z.string().optional().default(""),
  image_url: z.string(),
  buy_price: z.number(),
  sale_price: z.number(),
  quantity: z.number(),
  low_stock_threshold: z.number(),
  stock_state: z.enum(STOCK_STATES),
  active: z.boolean(),
});
export type ProductRow = z.infer<typeof productRowSchema>;

const pageSchema = z.object({
  success: z.literal(true),
  rows: z.array(productRowSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
  total_pages: z.number().int(),
  stats: z.object({ total: z.number(), available: z.number(), low: z.number(), out: z.number() }),
  categories: z.array(z.string()),
  brands: z.array(z.string()).optional().default([]),
  branch_scope_label: z.string(),
});
export type ProductsPage = z.infer<typeof pageSchema>;

const movementSchema = z.object({
  date: z.string().nullable().optional(),
  type: z.string(),
  type_ar: z.string().nullable().optional(),
  quantity_in: z.number().nullable().optional(),
  quantity_out: z.number().nullable().optional(),
  balance_after: z.number().nullable().optional(),
  description: z.string().nullable().optional(),
});
const movementsSchema = z.object({ movements: z.array(movementSchema) });
export type ProductMovement = z.infer<typeof movementSchema>;

const str = z
  .string()
  .nullable()
  .optional()
  .transform((value) => value ?? "");
const num = z
  .number()
  .nullable()
  .optional()
  .transform((value) => value ?? 0);

/** Tolerates FINORA rows with empty (null) columns — old products often have them. */
export const productDetailsSchema = z.object({
  id: z.number().int(),
  name: str,
  sku: str,
  barcode: str,
  buy_price: num,
  sale_price: num,
  exchange_sale_price: z.number().nullable().optional().default(null),
  trade_in_sales_enabled: z.boolean().optional(),
  editor_settings_supported: z.boolean().optional().default(false),
  pos_visible: z
    .boolean()
    .nullable()
    .optional()
    .transform((value) => value ?? true),
  store_visible: z
    .boolean()
    .nullable()
    .optional()
    .transform((value) => value ?? true),
  low_stock_threshold: num,
  description: str,
  image_url: str,
  active: z
    .boolean()
    .nullable()
    .optional()
    .transform((value) => value ?? true),
  has_colors: z
    .boolean()
    .nullable()
    .optional()
    .transform((value) => value ?? false),
  current_stock: num,
  colors_supported: z.boolean().optional().default(false),
  color_images_supported: z.boolean().optional().default(false),
  options_supported: z.boolean().optional(),
  option_axes: z.array(z.string()).optional(),
  colors: z
    .array(
      z.object({
        name: z.string(),
        qty: z.number(),
        image_url: str,
        id: z.number().optional(),
        attributes: z.record(z.string()).optional(),
        active: z.boolean().optional(),
        buy_price: z.number().nullable().optional(),
        sale_price: z.number().nullable().optional(),
        governorate_sale_price: z.number().nullable().optional(),
      }),
    )
    .optional()
    .default([]),
  category: str,
  brand: str,
  unit: str,
});
export type ProductDetails = z.infer<typeof productDetailsSchema>;

/** Fields the desktop editor sends; unset keys are not touched by FINORA's update adapter. */
export interface ProductFields {
  name?: string;
  sku?: string;
  barcode?: string;
  buy_price?: number;
  sale_price?: number;
  exchange_sale_price?: number;
  pos_visible?: boolean;
  store_visible?: boolean;
  low_stock_threshold?: number;
  category?: string;
  brand?: string;
  unit?: string;
  description?: string;
  active?: boolean;
  add_colors?: string[];
  color_stock?: number;
  product_options?: string;
}

export interface ImageUpload {
  name: string;
  type: "image/png" | "image/jpeg" | "image/webp" | "image/gif";
  data: Uint8Array;
}

export interface ColorImageChange {
  name: string;
  upload?: ImageUpload;
  remove?: boolean;
}
function colorImageFields(changes: ColorImageChange[]) {
  const actions = changes.map((change, index) =>
    change.upload
      ? { name: change.name, field: `color_image_${index}` }
      : { name: change.name, remove: true },
  );
  return {
    fields: changes.length ? [["color_images", JSON.stringify(actions)] as [string, string]] : [],
    files: changes.flatMap((change, index) =>
      change.upload ? [{ field: `color_image_${index}`, ...change.upload }] : [],
    ),
  };
}

function toFields(fields: ProductFields): Array<[string, string]> {
  return Object.entries(fields)
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => [
      key,
      Array.isArray(value)
        ? JSON.stringify(value)
        : typeof value === "boolean"
          ? value
            ? "1"
            : "0"
          : String(value),
    ]);
}

const savedSchema = z.object({ success: z.literal(true), product_id: z.number().int() }).passthrough();
const adjustedSchema = z.object({
  success: z.literal(true),
  message: z.string(),
  new_quantity: z.number(),
  new_sale_price: z.number(),
});

export interface ProductsQuery {
  page: number;
  pageSize: number;
  search?: string;
  category?: string;
  stock?: StockState;
  sortField?: "name" | "sku" | "category" | "buy_price" | "sale_price" | "quantity";
  sortDir?: "asc" | "desc";
}

/** FINORA image path → URL served by main through the FINORA session; null for anything else. */
export function productImageUrl(imageUrl: string, serverUrl: string | null): string | null {
  if (!imageUrl) return null;
  let path = imageUrl;
  if (/^https?:\/\//i.test(imageUrl)) {
    if (!serverUrl) return null;
    const url = new URL(imageUrl);
    if (url.origin !== new URL(serverUrl).origin) return null;
    path = url.pathname;
  }
  if (!path.startsWith("/")) path = `/${path}`;
  return `${MEDIA_SCHEME}://media${path}`;
}

export const products = {
  list(query: ProductsQuery): Promise<ProductsPage> {
    const params: Record<string, string | number> = {
      page: query.page,
      page_size: query.pageSize,
      sort_field: query.sortField ?? "name",
      sort_dir: query.sortDir ?? "asc",
    };
    if (query.search?.trim()) params.search = query.search.trim();
    if (query.category) params.category = query.category;
    if (query.stock) params.stock = query.stock;
    return finoraCall({ method: "GET", path: "/inventory/api/products", query: params }, pageSchema);
  },
  async movements(productId: number): Promise<ProductMovement[]> {
    const body = await finoraCall(
      { method: "GET", path: `/inventory/api/movements/${productId}` },
      movementsSchema,
    );
    return body.movements;
  },
  async details(productId: number): Promise<ProductDetails> {
    const body = await finoraCall(
      { method: "GET", path: `/inventory/api/products/${productId}` },
      z.object({ success: z.literal(true), product: productDetailsSchema }),
    );
    return body.product;
  },
  /** Creates through FINORA's own add-product form (opening stock, branch, audit) with a JSON reply. */
  create(
    fields: ProductFields & { opening_stock: number; colors?: { name: string; qty: number }[] },
    image?: ImageUpload,
    colorImages: ColorImageChange[] = [],
  ) {
    const { opening_stock, active, colors, ...rest } = fields;
    const formFields: Array<[string, string]> = [
      ["_response", "json"],
      ...toFields(rest),
      ["opening_stock", String(opening_stock)],
    ];
    if (active === false) formFields.push(["not_for_sale", "1"]);
    if (colors?.length) {
      formFields.push(["has_colors", "1"]);
      for (const color of colors)
        formFields.push(["color_name[]", color.name], ["color_qty[]", String(color.qty)]);
    }
    const media = colorImageFields(colorImages);
    return finoraForm(
      {
        path: "/inventory/add",
        fields: [...formFields, ...media.fields],
        file: image && { field: "product_image", ...image },
        files: media.files,
      },
      savedSchema,
    );
  },
  /** Updates only the given fields; specs, gallery, delivery fees and colours stay untouched. */
  update(
    productId: number,
    fields: ProductFields,
    image?: ImageUpload,
    colorImages: ColorImageChange[] = [],
  ) {
    const media = colorImageFields(colorImages);
    return finoraForm(
      {
        path: `/inventory/api/products/${productId}/update`,
        fields: [...toFields(fields), ...media.fields],
        file: image && { field: "product_image", ...image },
        files: media.files,
      },
      savedSchema,
    );
  },
  /** FINORA's stock adjustment: needs a reason, recorded as an inventory movement. */
  adjustStock(productId: number, adjustment: number, reason: string, colorName?: string) {
    return finoraCall(
      {
        method: "POST",
        path: `/inventory/adjust-stock/${productId}`,
        body: { adjustment, reason, ...(colorName ? { color_name: colorName } : {}) },
      },
      adjustedSchema,
    );
  },
  openInFinora(productId: number): Promise<void> {
    return desktopBridge().app.openInFinora(`/inventory/report/${productId}`);
  },
};
