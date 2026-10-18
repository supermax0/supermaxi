/** Shared POS query keys (window + idle prefetch must hash identically). */
export interface PosProductsQuery {
  page: number;
  pageSize: number;
  search: string;
  category?: string;
}

export const posKeys = {
  bootstrap: ["pos", "bootstrap"] as const,
  products: (query: PosProductsQuery) => ["pos", "products", query] as const,
};
