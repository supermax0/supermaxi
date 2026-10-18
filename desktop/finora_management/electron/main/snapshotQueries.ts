import type { FinoraRequest } from "../../shared/ipc";
import { OfflineSnapshot, type SnapshotRow } from "./offlineSnapshot";
import type { SnapshotDataset } from "../../shared/snapshot";

const text = (v: unknown) => String(v ?? "");
const num = (v: unknown) => Number(v ?? 0);
const lower = (v: unknown) => text(v).toLocaleLowerCase();
const matches = (row: SnapshotRow, search: string, fields: string[]) =>
  fields.some((field) => lower(row[field]).includes(search));
const orderTab = (row: SnapshotRow, tab: string) =>
  Array.isArray(row._offline_tabs) && row._offline_tabs.includes(tab);

/** Query only complete generations. Unavailable adapters fall back to the scoped response cache. */
export function snapshotQuery(
  snapshot: Pick<OfflineSnapshot, "active" | "rows" | "has">,
  request: FinoraRequest,
): unknown | undefined {
  const active = snapshot.active();
  if (!active || request.method !== "GET") return undefined;
  const q = request.query ?? {};
  const supported: Record<string, string[]> = {
    "/inventory/api/products": ["search", "category", "stock", "sort_field", "sort_dir", "page", "page_size"],
    "/pos/api/products": ["search", "category", "page", "page_size"],
    "/suppliers/api/page": ["search", "min_balance", "tab", "sort", "page", "page_size"],
    "/purchases/api/page": ["search", "supplier_id", "date_from", "date_to", "tab", "page", "page_size"],
    "/orders/data": [
      "search",
      "date_from",
      "date_to",
      "amount_min",
      "amount_max",
      "city",
      "shipping",
      "delivery_agent",
      "page_type",
      "page",
      "page_size",
      "sort_field",
      "sort_dir",
    ],
    "/orders/api/counts": [
      "search",
      "date_from",
      "date_to",
      "amount_min",
      "amount_max",
      "city",
      "shipping",
      "delivery_agent",
    ],
    "/suppliers/api/sale-products": ["q"],
    "/purchases/api/products/search": ["q"],
    "/pos/search-customer": ["q", "branch_id"],
  };
  if (Object.keys(q).some((key) => !(supported[request.path] ?? []).includes(key))) return undefined;
  if (
    request.path === "/pos/search-customer" &&
    q.branch_id !== undefined &&
    Number(q.branch_id) !== active.manifest.branch_id
  )
    return undefined;
  const value = (key: string) => text(q[key]);
  const search = lower(q.search ?? q.q).trim();
  const definition = (name: SnapshotDataset) => active.manifest.datasets.find((d) => d.name === name);
  const paginate = (rows: SnapshotRow[], meta: Record<string, unknown>, maximum = 100, defaultSize = 25) => {
    const size = Math.min(maximum, Math.max(1, Math.trunc(num(q.page_size) || defaultSize)));
    const pages = Math.max(1, Math.ceil(rows.length / size));
    const page = Math.min(pages, Math.max(1, Math.trunc(num(q.page) || 1)));
    return {
      ...meta,
      success: true,
      rows: rows.slice((page - 1) * size, page * size),
      page,
      page_size: size,
      total: rows.length,
      total_pages: pages,
    };
  };
  const detail = request.path.match(
    /^\/(inventory\/api\/products|suppliers\/api|purchases\/api|orders\/details)\/(\d+)$/,
  );
  if (detail) {
    const dataset: SnapshotDataset =
      detail[1] === "inventory/api/products"
        ? "product-details"
        : detail[1] === "suppliers/api"
          ? "supplier-details"
          : detail[1] === "purchases/api"
            ? "purchase-details"
            : "order-details";
    return snapshot.rows(dataset).find((r) => r.id === Number(detail[2]))?.value;
  }
  const staticDataset: Partial<Record<string, SnapshotDataset>> = {
    "/orders/api/lookups": "order-lookups",
    "/pos/api/bootstrap": "pos-bootstrap",
    "/orders/payment-accounts": "payment-accounts",
  };
  const staticName = staticDataset[request.path];
  if (staticName) return snapshot.rows(staticName)[0]?.value;
  if (
    request.path === "/suppliers/api/sale-products" ||
    request.path === "/purchases/api/products/search" ||
    request.path === "/pos/search-customer"
  ) {
    const dataset =
      request.path === "/pos/search-customer"
        ? "customers"
        : request.path === "/purchases/api/products/search"
          ? "purchase-products"
          : "supplier-products";
    if (!snapshot.has(dataset)) return undefined;
    if (!search) return [];
    const rows = snapshot.rows(dataset);
    const exact = dataset !== "customers" && rows.find((row) => row.barcode === value("q"));
    return exact
      ? [exact]
      : rows
          .filter((row) =>
            matches(
              row,
              search,
              dataset === "customers" ? ["name", "phone", "phone2"] : ["name", "sku", "barcode"],
            ),
          )
          .slice(0, 15);
  }
  if (request.path === "/inventory/api/products" || request.path === "/pos/api/products") {
    const name = request.path.startsWith("/pos/") ? "pos-products" : "products";
    const dataset = definition(name);
    if (!dataset) return undefined;
    let rows = snapshot.rows(name);
    if (search)
      rows = rows.filter(
        (r) =>
          lower(r.name).includes(search) ||
          lower(r.sku).includes(search) ||
          lower(r.barcode) === search ||
          (search.length >= 4 && lower(r.barcode).includes(search)),
      );
    if (q.category) rows = rows.filter((r) => r.category === q.category);
    if (["available", "low", "out"].includes(value("stock")))
      rows = rows.filter((r) => r.stock_state === q.stock);
    const field = ["name", "sku", "category", "buy_price", "sale_price", "quantity"].includes(
      value("sort_field"),
    )
      ? value("sort_field")
      : "name";
    if (name === "products")
      rows.sort(
        (a, b) =>
          (typeof a[field] === "number"
            ? num(a[field]) - num(b[field])
            : lower(a[field]).localeCompare(lower(b[field]))) * (q.sort_dir === "desc" ? -1 : 1),
      );
    return paginate(rows, dataset.meta, name === "products" ? 100 : 60, name === "products" ? 25 : 24);
  }
  if (request.path === "/suppliers/api/page") {
    const dataset = definition("suppliers");
    if (!dataset) return undefined;
    let rows = snapshot.rows("suppliers");
    if (search) rows = rows.filter((r) => matches(r, search, ["name", "phone", "phone2", "address"]));
    if (num(q.min_balance) > 0) rows = rows.filter((r) => Math.abs(num(r.remaining)) >= num(q.min_balance));
    const counts = {
      all: rows.length,
      debt: rows.filter((r) => num(r.remaining) > 0).length,
      credit: rows.filter((r) => num(r.remaining) < 0).length,
      settled: rows.filter((r) => num(r.remaining) === 0).length,
    };
    if (q.tab && q.tab !== "all")
      rows = rows.filter((r) =>
        q.tab === "debt"
          ? num(r.remaining) > 0
          : q.tab === "credit"
            ? num(r.remaining) < 0
            : num(r.remaining) === 0,
      );
    rows.sort((a, b) => lower(a.name).localeCompare(lower(b.name)) || a.id - b.id);
    if (q.sort === "balance") rows.sort((a, b) => Math.abs(num(b.remaining)) - Math.abs(num(a.remaining)));
    if (q.sort === "recent")
      rows.sort((a, b) => text(b.last_transaction).localeCompare(text(a.last_transaction)));
    return paginate(rows, { ...dataset.meta, counts });
  }
  if (request.path === "/purchases/api/page") {
    const dataset = definition("purchases");
    if (!dataset) return undefined;
    let rows = snapshot
      .rows("purchases")
      .filter(
        (r) =>
          (!q.supplier_id || r.supplier_id === num(q.supplier_id)) &&
          (!q.date_from || text(r.date).slice(0, 10) >= value("date_from")) &&
          (!q.date_to || text(r.date).slice(0, 10) <= value("date_to")),
      );
    if (search)
      rows = rows.filter((r) =>
        matches(r, search, ["invoice_no", "supplier_invoice_no", "supplier", "first_product"]),
      );
    const counts: Record<string, number> = { all: rows.length };
    for (const tab of ["draft", "confirmed", "unpaid", "cancelled"])
      counts[tab] = rows.filter((r) => r.tab === tab).length;
    const nonCancelled = rows.filter((r) => r.tab !== "cancelled");
    const summary = {
      count: nonCancelled.length,
      total_amount: nonCancelled.filter((r) => r.tab !== "draft").reduce((n, r) => n + num(r.grand_total), 0),
      draft: counts.draft,
      unpaid: counts.unpaid,
      remaining_amount: nonCancelled.reduce((n, r) => n + num(r.remaining_total), 0),
    };
    if (q.tab && q.tab !== "all") rows = rows.filter((r) => r.tab === q.tab);
    return paginate(rows, { ...dataset.meta, counts, summary });
  }
  if (request.path === "/orders/data" || request.path === "/orders/api/counts") {
    const dataset = definition("orders");
    const allowed = snapshot.rows("order-counts")[0]?.value as
      { counts?: Record<string, number> } | undefined;
    if (!dataset || !allowed?.counts) return undefined;
    const tab = value("page_type") || "all";
    if (!(tab in allowed.counts)) return undefined;
    let rows = snapshot.rows("orders");
    if (search)
      rows = rows.filter((r) =>
        matches(r, search, ["id", "customer_name", "phone", "phone2", "barcode", "shipping_barcode", "note"]),
      );
    rows = rows.filter(
      (r) =>
        (!q.date_from || text(r.date).slice(0, 10) >= value("date_from")) &&
        (!q.date_to || text(r.date).slice(0, 10) <= value("date_to")) &&
        (q.amount_min === undefined || num(r.total) >= num(q.amount_min)) &&
        (q.amount_max === undefined || num(r.total) <= num(q.amount_max)) &&
        (!q.city || (Array.isArray(q.city) ? q.city : [q.city]).includes(text(r.city))) &&
        (!q.shipping || r.shipping_company === q.shipping) &&
        (!q.delivery_agent ||
          (q.delivery_agent === "none"
            ? r.delivery_agent_id === null
            : r.delivery_agent === q.delivery_agent)),
    );
    const counts = Object.fromEntries(
      Object.keys(allowed.counts).map((key) => [key, rows.filter((r) => orderTab(r, key)).length]),
    );
    if (request.path === "/orders/api/counts") return { success: true, counts };
    rows = rows.filter((r) => orderTab(r, tab));
    const field = value("sort_field") === "order_id" ? "id" : value("sort_field") || "date";
    rows.sort(
      (a, b) =>
        (typeof a[field] === "number"
          ? num(a[field]) - num(b[field])
          : text(a[field]).localeCompare(text(b[field]))) * (q.sort_dir === "asc" ? 1 : -1) || b.id - a.id,
    );
    return paginate(
      rows,
      {
        total_amount: rows.reduce((n, r) => n + num(r.total), 0),
        total_quantity: rows.reduce((n, r) => n + num(r.quantity), 0),
      },
      500,
      100,
    );
  }
  return undefined;
}
