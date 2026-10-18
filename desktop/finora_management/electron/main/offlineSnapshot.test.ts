import { createHash, randomBytes } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
import type { SnapshotManifest } from "../../shared/snapshot";
import { OfflineDatabase } from "./offlineDatabase";
import { OfflineEngine } from "./offlineEngine";

const SESSION_PATH = "/api/v1/desktop/auth/session";
const session = {
  user: { id: 1, name: "Employee", username: "employee", role: "admin" },
  tenant: { id: 1, slug: "tenant", name: "Tenant", business_type: "general" },
  branch: { id: 1, name: "Main" },
  branch_scope: "branch",
  roles: ["admin"],
  permissions: ["can_manage_suppliers"],
  session_max_age_seconds: 604800,
};
const product = {
  id: 10,
  name: "Offline television",
  sku: "TV",
  barcode: "9001",
  quantity: 5,
  sale_price: 300,
  has_colors: false,
  colors: [],
};
let directory: string;
let store: OfflineDatabase;
let key: Buffer;
const wasm = path.resolve("node_modules/sql.js/dist/sql-wasm.wasm");
beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-snapshot-test-"));
  key = randomBytes(32);
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
});
afterEach(async () => {
  await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-snapshot-test-")
  )
    throw new Error("Unsafe test cleanup");
  await fs.rm(directory, { recursive: true, force: true });
});

function fixture() {
  let online = true;
  let count = 1;
  let failCursor: number | null = null;
  let corrupt = false;
  let denied = false;
  const manifests = new Map<string, SnapshotManifest>();
  const captured = new Map<string, (typeof product)[]>();
  const sender = vi.fn(async (request: FinoraRequest): Promise<FinoraResponse> => {
    if (!online) return { ok: false, failure: "network" };
    if (request.path === SESSION_PATH) return { ok: true, status: 200, data: { ok: true, session } };
    if (request.path === "/api/v1/desktop/snapshots") {
      const id = String((request.body as { id: string }).id);
      if (!manifests.has(id)) {
        manifests.set(id, {
          success: true,
          version: 1,
          id,
          tenant_slug: "tenant",
          user_id: 1,
          branch_id: 1,
          branch_scope: "branch",
          permissions: session.permissions,
          started_at: Date.now(),
          captured_at: Date.now(),
          expires_at: Date.now() + 86400000,
          datasets: [{ name: "supplier-products", total: count, page_size: 100, meta: {} }],
        });
        captured.set(
          id,
          Array.from({ length: count }, (_, index) => ({
            ...product,
            id: product.id + index,
            name: `${product.name} ${index}`,
            barcode: String(9001 + index),
          })),
        );
      }
      return { ok: true, status: 200, data: manifests.get(id) };
    }
    const match = request.path.match(/^\/api\/v1\/desktop\/snapshots\/([^/]+)\/supplier-products$/);
    if (match) {
      if (denied) return { ok: false, failure: "http", status: 403, data: { error: "revoked" } };
      const cursor = Number(request.query?.cursor);
      if (cursor === failCursor) return { ok: false, failure: "network" };
      const generation = captured.get(match[1] ?? "");
      if (!generation) throw new Error("Unknown fixture snapshot");
      const rows = generation.slice(cursor, cursor + 100);
      const rowsJson = JSON.stringify(rows);
      return {
        ok: true,
        status: 200,
        data: {
          success: true,
          id: match[1],
          dataset: "supplier-products",
          cursor,
          next_cursor: cursor + rows.length,
          rows_json: rowsJson,
          digest: corrupt ? "0".repeat(64) : createHash("sha256").update(rowsJson).digest("hex"),
        },
      };
    }
    return { ok: false, failure: "http", status: 404, data: {} };
  });
  const engine = () => new OfflineEngine(store, "https://finora.test", sender);
  return {
    sender,
    engine,
    setCount: (value: number) => {
      count = value;
    },
    setOnline: (value: boolean) => {
      online = value;
    },
    failAt: (value: number | null) => {
      failCursor = value;
    },
    corrupt: (value = true) => {
      corrupt = value;
    },
    deny: () => {
      denied = true;
    },
  };
}
const search = (q: string): FinoraRequest => ({
  method: "GET",
  path: "/suppliers/api/sale-products",
  query: { q },
});

it("serves an unvisited product search after an encrypted offline restart", async () => {
  const f = fixture();
  f.setCount(205);
  let engine = f.engine();
  await engine.downloadSnapshot();
  expect(engine.status().snapshot).toMatchObject({ downloaded: 205, total: 205, resumable: false });
  expect((await fs.readFile(path.join(directory, "local.enc"))).toString()).not.toContain(
    "Offline television",
  );
  await store.close();
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
  engine = f.engine();
  f.setOnline(false);
  expect(await engine.request(search("9205"))).toMatchObject({
    ok: true,
    source: "offline",
    data: [{ id: 214, barcode: "9205" }],
  });
  await expect(
    engine.saveSupplierDraft({
      supplierId: 7,
      supplierName: "Supplier",
      items: [{ product_id: 214, qty: 1, price: 300 }],
      note: "",
    }),
  ).resolves.toHaveProperty("id");
});

it("preserves the old complete generation, resumes committed pages after restart and removes deleted records", async () => {
  const f = fixture();
  f.setCount(205);
  let engine = f.engine();
  await engine.downloadSnapshot();
  const oldDate = engine.status().snapshot?.capturedAt;
  f.setCount(101);
  f.failAt(100);
  await expect(engine.downloadSnapshot()).rejects.toThrow("تقدّمك محفوظ");
  expect(engine.status().snapshot).toMatchObject({
    capturedAt: oldDate,
    downloaded: 100,
    total: 101,
    resumable: true,
  });
  f.setOnline(false);
  expect((await engine.request(search("9205"))).ok).toBe(true);
  await store.close();
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
  engine = f.engine();
  f.setOnline(true);
  f.failAt(null);
  f.sender.mockClear();
  await engine.downloadSnapshot();
  const cursors = f.sender.mock.calls
    .filter(([r]) => r.path.endsWith("/supplier-products"))
    .map(([r]) => r.query?.cursor);
  expect(cursors).toEqual([100]);
  f.setOnline(false);
  expect(await engine.request(search("9205"))).toMatchObject({ ok: true, source: "offline", data: [] });
  expect(engine.status().snapshot).toMatchObject({ downloaded: 101, total: 101, resumable: false });
});

it("refuses a corrupted page without replacing the complete snapshot", async () => {
  const f = fixture();
  const engine = f.engine();
  await engine.downloadSnapshot();
  const captured = engine.status().snapshot?.capturedAt;
  f.corrupt();
  f.setCount(10);
  await expect(engine.downloadSnapshot()).rejects.toThrow("فشل التحقق");
  expect(engine.status().snapshot).toMatchObject({
    capturedAt: captured,
    downloaded: 0,
    total: 10,
    resumable: true,
  });
  f.setOnline(false);
  expect(await engine.request(search("9001"))).toMatchObject({
    ok: true,
    source: "offline",
    data: [{ id: 10 }],
  });
  f.setOnline(true);
  f.corrupt(false);
  await engine.downloadSnapshot(true);
  expect(engine.status().snapshot).toMatchObject({ downloaded: 10, total: 10, resumable: false });
});

it("revokes offline access when the server denies a download page", async () => {
  const f = fixture();
  const engine = f.engine();
  await engine.downloadSnapshot();
  f.deny();
  await expect(engine.downloadSnapshot()).rejects.toThrow();
  expect(engine.status().available).toBe(false);
  f.setOnline(false);
  expect((await engine.request(search("9001"))).ok).toBe(false);
});

it("does not expose a complete generation under another user's session", async () => {
  const f = fixture();
  const engine = f.engine();
  await engine.downloadSnapshot();
  await engine.request({ method: "GET", path: SESSION_PATH }, async () => ({
    ok: true,
    status: 200,
    data: { ok: true, session: { ...session, user: { ...session.user, id: 2 } } },
  }));
  expect(engine.status().snapshot?.capturedAt).toBeNull();
  f.setOnline(false);
  expect((await engine.request(search("9001"))).ok).toBe(false);
});
