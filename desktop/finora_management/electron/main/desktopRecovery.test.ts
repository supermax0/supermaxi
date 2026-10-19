import { randomBytes, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { OfflineDatabase, replaceFile } from "./offlineDatabase";
import { openBackup, sealBackup } from "./backupCrypto";
import { exportScoped, importScoped, restoreBlocked } from "./portableStore";
import { windowGeometry } from "./windowGeometry";
import { OfflineEngine } from "./offlineEngine";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";

let directory: string;
const stores: OfflineDatabase[] = [];
const scope = "a".repeat(64),
  other = "b".repeat(64),
  server = "https://finora.test";
async function database() {
  const store = await OfflineDatabase.open(
    path.join(directory, `${randomUUID()}.enc`),
    randomBytes(32),
    path.resolve("node_modules/sql.js/dist/sql-wasm.wasm"),
  );
  stores.push(store);
  return store;
}
beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-recovery-"));
});
afterEach(async () => {
  for (const store of stores.splice(0)) await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-recovery-")
  )
    throw Error("Unsafe cleanup");
  await fs.rm(directory, { recursive: true, force: true });
});
it("retries transient Windows locks with a bounded delay and never deletes the old checkpoint", async () => {
  const rename = vi
    .fn<typeof fs.rename>()
    .mockRejectedValueOnce(Object.assign(Error("locked"), { code: "EPERM" }))
    .mockResolvedValue(undefined);
  const pause = vi.fn(async () => undefined);
  await replaceFile("temporary", "original", rename, pause);
  expect(rename).toHaveBeenCalledTimes(2);
  expect(pause).toHaveBeenCalledWith(40);
  rename.mockReset().mockRejectedValue(Object.assign(Error("locked"), { code: "EACCES" }));
  await expect(replaceFile("temporary", "original", rename, pause)).rejects.toThrow("locked");
  expect(rename).toHaveBeenCalledTimes(7);
  rename.mockReset().mockRejectedValue(Object.assign(Error("full"), { code: "ENOSPC" }));
  await expect(replaceFile("temporary", "original", rename, pause)).rejects.toThrow("full");
  expect(rename).toHaveBeenCalledTimes(1);
});
it("authenticates portable backups independently from the Windows device key", async () => {
  const data = Buffer.from("private financial journal");
  const encrypted = await sealBackup(data, "a long private password");
  expect(encrypted.includes(data)).toBe(false);
  expect(await openBackup(encrypted, "a long private password")).toEqual(data);
  await expect(openBackup(encrypted, "different password")).rejects.toThrow();
  const corrupt = Buffer.from(encrypted);
  corrupt[corrupt.length - 1] = (corrupt[corrupt.length - 1] ?? 0) ^ 1;
  await expect(openBackup(corrupt, "a long private password")).rejects.toThrow();
  await expect(openBackup(Buffer.from("wrong header"), "a long private password")).rejects.toThrow();
});
it("exports only the current scope and preserves pending operation identities, receipts and frozen quota", async () => {
  const source = await database(),
    target = await database(),
    id = randomUUID(),
    allocation = randomUUID();
  await source.write(() => {
    source.run("INSERT INTO responses VALUES (?,?,?,1)", [scope, "own", "private"]);
    source.run("INSERT INTO responses VALUES (?,?,?,1)", [other, "other", "secret"]);
    source.run("INSERT INTO operations VALUES (?,?,?,'sale',10,1,'pending',NULL,NULL)", [id, scope, "{}"]);
    source.run("INSERT INTO operation_reservations VALUES (?,?,'receipt')", [id, "[]"]);
    source.run("INSERT INTO device_stock VALUES (?,?,?,1,'TV','',2,1,0,0)", [
      allocation,
      scope,
      randomUUID(),
    ]);
  });
  const backup = await exportScoped(source, server, scope, ["view_pos"]);
  expect(JSON.stringify(backup)).not.toContain("secret");
  await importScoped(target, backup, server, scope, ["view_pos"]);
  expect(target.one("SELECT id FROM operations")?.id).toBe(id);
  expect(target.one("SELECT receipt FROM operation_reservations")?.receipt).toBe("receipt");
  expect(target.one("SELECT frozen FROM device_stock")?.frozen).toBe(1);
  expect(target.one("SELECT value FROM metadata WHERE key=?", [`restored-stock:${scope}`])?.value).toBe("1");
  expect(target.one("SELECT value FROM metadata WHERE key='device'")?.value).toBe(backup.device);
});
it("rejects wrong account, server, permissions and foreign rows without changing the target", async () => {
  const source = await database(),
    target = await database();
  const backup = await exportScoped(source, server, scope, ["view_pos"]);
  for (const [host, own, permissions] of [
    [server, other, ["view_pos"]],
    ["https://other.test", scope, ["view_pos"]],
    [server, scope, []],
  ] as const)
    await expect(importScoped(target, backup, host, own, [...permissions])).rejects.toThrow();
  backup.tables.responses = [{ scope: other, key: "bad", body: "private", saved: 1 }];
  await expect(importScoped(target, backup, server, scope, ["view_pos"])).rejects.toThrow();
  expect(target.all("SELECT * FROM responses")).toEqual([]);
});
it("does not overwrite pending work and rolls back invalid archived rows atomically", async () => {
  const source = await database(),
    target = await database();
  const backup = await exportScoped(source, server, scope, []);
  await target.write(() =>
    target.run("INSERT INTO operations VALUES (?,?,?,'pending',1,1,'pending',NULL,NULL)", [
      randomUUID(),
      scope,
      "{}",
    ]),
  );
  await expect(importScoped(target, backup, server, scope, [])).rejects.toThrow();
  expect(target.all("SELECT * FROM operations")).toHaveLength(1);
  const fresh = await database();
  backup.tables.responses = [
    { scope, key: "same", body: "one", saved: 1 },
    { scope, key: "same", body: "two", saved: 2 },
  ];
  await expect(importScoped(fresh, backup, server, scope, [])).rejects.toThrow();
  expect(fresh.all("SELECT * FROM responses")).toHaveLength(0);
});
it.each([
  { width: 1920, height: 1080 },
  { width: 1024, height: 600 },
  { width: 640, height: 360 },
])("fits the Windows work area at $width × $height", (area) => {
  const result = windowGeometry(area);
  expect(result.width).toBeLessThanOrEqual(area.width);
  expect(result.height).toBeLessThanOrEqual(area.height);
  expect(result.minWidth).toBeLessThanOrEqual(result.width);
  expect(result.minHeight).toBeLessThanOrEqual(result.height);
});

async function recoveredFixture() {
  const store = await database(),
    allocation = randomUUID(),
    grant = randomUUID();
  let failReturn = false,
    returned = 1;
  const processed = new Set<string>();
  const returnedIds: string[] = [];
  const session = {
    user: { id: 1, name: "Cashier", username: "cashier", role: "cashier" },
    tenant: { id: 1, slug: "tenant", name: "Company", business_type: "general" },
    branch: { id: 1, name: "Main" },
    roles: ["cashier"],
    permissions: ["view_pos"],
    session_max_age_seconds: 604800,
    offline_pos_enabled: true,
  };
  const sender = vi.fn(async (request: FinoraRequest): Promise<FinoraResponse> => {
    if (request.path.endsWith("auth/session")) return { ok: true, status: 200, data: { ok: true, session } };
    if (request.path.endsWith("stock/device"))
      return {
        ok: true,
        status: 200,
        data: {
          success: true,
          allocations: [
            {
              id: allocation,
              grant_id: grant,
              product_id: 1,
              name: "TV",
              color: "",
              quantity: 4,
              used: 1,
              returned,
            },
          ],
        },
      };
    if (request.path.endsWith("stock/return")) {
      const payload = request.body as { id: string; parts: { id: string; qty: number }[] };
      expect(payload.parts).toEqual([{ id: allocation, qty: 2 }]);
      returnedIds.push(payload.id);
      if (!processed.has(payload.id)) {
        returned += 2;
        processed.add(payload.id);
      }
      if (failReturn) return { ok: false, failure: "network" };
      return { ok: true, status: 200, data: { success: true, id: payload.id } };
    }
    throw Error(request.path);
  });
  const engine = new OfflineEngine(store, server, sender);
  await engine.request({ method: "GET", path: "/api/v1/desktop/auth/session" });
  const own = engine.backupContext().id;
  await store.write(() => {
    store.run("INSERT INTO metadata VALUES (?, '1')", [`restored-stock:${own}`]);
    store.run("INSERT INTO device_stock VALUES (?,?,?,1,'TV','',10,0,0,1)", [allocation, own, grant]);
  });
  return {
    store,
    engine,
    own,
    sender,
    returnedIds,
    failReturn: (value: boolean) => {
      failReturn = value;
    },
  };
}
it("reconciles the authoritative remaining quota once even with concurrent sync calls", async () => {
  const f = await recoveredFixture();
  await Promise.all([f.engine.reconcileRestoredQuota(), f.engine.reconcileRestoredQuota()]);
  expect(f.returnedIds).toHaveLength(1);
  expect(f.store.one("SELECT quantity-used-returned AS available FROM device_stock")?.available).toBe(0);
  expect(f.store.one("SELECT value FROM metadata WHERE key=?", [`restored-stock:${f.own}`])).toBeUndefined();
});
it("keeps restored stock frozen after an uncertain return and resumes the same request identity", async () => {
  const f = await recoveredFixture();
  f.failReturn(true);
  await expect(f.engine.reconcileRestoredQuota()).rejects.toThrow();
  expect(f.store.one("SELECT frozen FROM device_stock")?.frozen).toBe(1);
  expect(f.store.one("SELECT state FROM stock_requests")?.state).toBe("pending");
  await f.engine.reconcileRestoredQuota();
  expect(f.returnedIds).toHaveLength(1);
  f.failReturn(false);
  await f.engine.manageStock("resume");
  expect(f.returnedIds).toHaveLength(2);
  expect(f.returnedIds[0]).toBe(f.returnedIds[1]);
});

it("refuses to abandon unused grants of the target device or another account during restore", async () => {
  const store = await database(),
    device = String(store.one("SELECT value FROM metadata WHERE key='device'")?.value);
  await store.write(() =>
    store.run("INSERT INTO device_stock VALUES (?,?,?,1,'TV','',2,0,0,0)", [
      randomUUID(),
      scope,
      randomUUID(),
    ]),
  );
  expect(restoreBlocked(store, scope, randomUUID())).toBe(true);
  expect(restoreBlocked(store, scope, device)).toBe(false);
  expect(restoreBlocked(store, other, device)).toBe(true);
});
