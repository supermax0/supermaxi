import { randomUUID } from "node:crypto";
import type { SnapshotDataset, SnapshotManifest } from "../../shared/snapshot";
import type { OfflineSnapshot, SnapshotRow } from "./offlineSnapshot";
import type { FinoraRequest } from "../../shared/ipc";
import { snapshotQuery } from "./snapshotQueries";

function query(
  data: Partial<Record<SnapshotDataset, SnapshotRow[]>>,
  path: string,
  params: FinoraRequest["query"] = {},
  meta: Partial<Record<SnapshotDataset, Record<string, unknown>>> = {},
) {
  const id = randomUUID();
  const manifest: SnapshotManifest = {
    success: true,
    version: 1,
    id,
    tenant_slug: "tenant",
    user_id: 1,
    branch_id: 2,
    branch_scope: "branch",
    permissions: [],
    started_at: 1,
    captured_at: 2,
    expires_at: Date.now() + 10000,
    datasets: (Object.keys(data) as SnapshotDataset[]).map((name) => ({
      name,
      total: data[name]?.length ?? 0,
      page_size: 100,
      meta: meta[name] ?? {},
    })),
  };
  const snapshot: Pick<OfflineSnapshot, "active" | "rows" | "has"> = {
    active: () => ({ scope: "scope", id, stale: false, manifest }),
    rows: (name) => data[name] ?? [],
    has: (name) => name in data,
  };
  return snapshotQuery(snapshot, { method: "GET", path, query: params });
}

it("filters supplier balances and preserves global summary while paging local matches", () => {
  const suppliers = [
    { id: 1, name: "A", phone: "0771", remaining: 100 },
    { id: 2, name: "B", phone: "0772", remaining: -50 },
    { id: 3, name: "C", phone: "0783", remaining: 0 },
  ];
  expect(
    query(
      { suppliers },
      "/suppliers/api/page",
      { search: "077", sort: "balance", page_size: 1, page: 2 },
      { suppliers: { summary: { count: 3 } } },
    ),
  ).toMatchObject({
    rows: [{ id: 2 }],
    total: 2,
    total_pages: 2,
    counts: { all: 2, debt: 1, credit: 1, settled: 0 },
    summary: { count: 3 },
  });
  expect(query({ suppliers }, "/suppliers/api/page", { min_balance: 80, tab: "debt" })).toMatchObject({
    rows: [{ id: 1 }],
    total: 1,
  });
});

it("calculates purchase totals with date/supplier filters and excludes cancelled documents", () => {
  const purchases = [
    { id: 1, supplier_id: 2, date: "2026-10-09", tab: "unpaid", grand_total: 300, remaining_total: 100 },
    { id: 2, supplier_id: 2, date: "2026-10-08", tab: "draft", grand_total: 700, remaining_total: 700 },
    { id: 3, supplier_id: 2, date: "2026-10-07", tab: "cancelled", grand_total: 1000, remaining_total: 1000 },
    { id: 4, supplier_id: 3, date: "2026-10-09", tab: "confirmed", grand_total: 900, remaining_total: 0 },
  ];
  expect(
    query({ purchases }, "/purchases/api/page", { supplier_id: 2, date_from: "2026-10-08", tab: "unpaid" }),
  ).toMatchObject({
    rows: [{ id: 1 }],
    counts: { all: 2, draft: 1, unpaid: 1, cancelled: 0 },
    summary: { count: 2, total_amount: 300, remaining_amount: 800 },
  });
});

it("uses server-exported order tab memberships and honors overlapping paid tabs and permissions", () => {
  const data: Partial<Record<SnapshotDataset, SnapshotRow[]>> = {
    orders: [
      {
        id: 1,
        total: 100,
        date: "2026-10-09",
        city: "بغداد",
        _offline_tabs: ["all", "ordered", "delivered"],
      },
      { id: 2, total: 200, date: "2026-10-08", city: "البصرة", _offline_tabs: ["all", "packed"] },
    ],
    "order-counts": [{ id: 0, value: { counts: { all: 2, ordered: 1, packed: 1, delivered: 1 } } }],
  };
  expect(query(data, "/orders/api/counts", { city: ["بغداد"] })).toEqual({
    success: true,
    counts: { all: 1, ordered: 1, packed: 0, delivered: 1 },
  });
  expect(query(data, "/orders/data", { page_type: "delivered", amount_max: 150 })).toMatchObject({
    rows: [{ id: 1 }],
    total_amount: 100,
  });
  expect(query(data, "/orders/data", { page_type: "returned" })).toBeUndefined();
  expect(query(data, "/orders/data", { installment_type: "installment" })).toBeUndefined();
});

it("keeps exact barcode priority and does not answer searches for another branch", () => {
  const data: Partial<Record<SnapshotDataset, SnapshotRow[]>> = {
    "supplier-products": [
      { id: 1, name: "9001 television", barcode: "other" },
      { id: 2, name: "Screen", barcode: "9001" },
    ],
    customers: [{ id: 3, name: "أحمد", phone: "0771" }],
  };
  expect(query(data, "/suppliers/api/sale-products", { q: "9001" })).toEqual([
    { id: 2, name: "Screen", barcode: "9001" },
  ]);
  expect(query(data, "/pos/search-customer", { q: "أحمد", branch_id: 3 })).toBeUndefined();
  expect(query(data, "/pos/search-customer", { q: "أحمد", branch_id: 2 })).toMatchObject([{ id: 3 }]);
});
