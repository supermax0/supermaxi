import { randomBytes, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { stockGrantSchema } from "../../shared/stock";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
import { OfflineDatabase } from "./offlineDatabase";
import { OfflineEngine } from "./offlineEngine";

const session = {
  user: { id: 1, name: "Employee", username: "employee", role: "admin" },
  tenant: { id: 1, slug: "tenant", name: "Private company", business_type: "general" },
  branch: { id: 1, name: "Main" },
  roles: ["admin"],
  permissions: ["can_manage_suppliers"],
  session_max_age_seconds: 604800,
};
const input = [{ product_id: 10, qty: 1, variant_color: "أسود" }];
const sale = {
  supplierId: 7,
  supplierName: "Supplier",
  items: [{ ...input[0], product_id: 10, qty: 1, price: 300, variant_color: "أسود" }],
  note: "",
  stockMode: "reserved" as const,
};
const wasm = path.resolve("node_modules/sql.js/dist/sql-wasm.wasm");
let directory: string, store: OfflineDatabase, key: Buffer;
beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-quota-test-"));
  key = randomBytes(32);
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
});
afterEach(async () => {
  vi.restoreAllMocks();
  await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-quota-test-")
  )
    throw new Error("Unsafe cleanup");
  await fs.rm(directory, { recursive: true, force: true });
});
function fixture() {
  let online = true,
    loseReserve = false,
    loseReturn = false,
    loseSync = false;
  const grants = new Map<string, unknown>(),
    returns = new Map<string, unknown>(),
    receipts = new Map<string, unknown>();
  const requests: FinoraRequest[] = [];
  const sender = vi.fn(async (request: FinoraRequest): Promise<FinoraResponse> => {
    requests.push(request);
    if (!online) return { ok: false, failure: "network" };
    if (request.path === "/api/v1/desktop/auth/session")
      return { ok: true, status: 200, data: { ok: true, session } };
    const body = request.body as { id: string; device_id: string; operation_id: string };
    if (request.path.endsWith("/stock/reserve")) {
      if (!grants.has(body.id))
        grants.set(body.id, {
          success: true,
          id: body.id,
          device_id: body.device_id,
          employee_id: 1,
          branch_id: 1,
          allocations: [
            {
              id: randomUUID(),
              product_id: 10,
              name: "Private television",
              variant_color: "أسود",
              quantity: 1,
              sale_price: 300,
            },
          ],
        });
      if (loseReserve) {
        loseReserve = false;
        return { ok: false, failure: "network" };
      }
      return { ok: true, status: 200, data: grants.get(body.id) };
    }
    if (request.path.endsWith("/stock/return")) {
      returns.set(body.id, { success: true, id: body.id });
      if (loseReturn) {
        loseReturn = false;
        return { ok: false, failure: "network" };
      }
      return { ok: true, status: 200, data: returns.get(body.id) };
    }
    if (request.path.endsWith("/sync/supplier-sale")) {
      if (!receipts.has(body.operation_id))
        receipts.set(body.operation_id, { success: true, invoice_no: "SS-1" });
      if (loseSync) {
        loseSync = false;
        return { ok: false, failure: "network" };
      }
      return { ok: true, status: 200, data: receipts.get(body.operation_id) };
    }
    throw new Error(`Unexpected ${request.path}`);
  });
  return {
    sender,
    requests,
    receipts,
    grants,
    newEngine: () => new OfflineEngine(store, "https://finora.test", sender),
    offline: () => {
      online = false;
    },
    online: () => {
      online = true;
    },
    loseReserve: () => {
      loseReserve = true;
    },
    loseReturn: () => {
      loseReturn = true;
    },
    loseSync: () => {
      loseSync = true;
    },
  };
}
async function reopen() {
  await store.close();
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
}
it("recovers an uncertain reservation with its original UUID, then sells one piece durably offline", async () => {
  const f = fixture();
  let engine = f.newEngine();
  await engine.request({ method: "GET", path: "/api/v1/desktop/auth/session" });
  f.loseReserve();
  await expect(engine.manageStock("reserve", input)).rejects.toThrow();
  expect(engine.status().stock?.pendingRequest).toBe(true);
  expect(engine.status().stock?.rows).toEqual([]);
  await reopen();
  engine = f.newEngine();
  await engine.manageStock("resume");
  expect(f.grants.size).toBe(1);
  expect(engine.status().stock?.rows[0]?.available).toBe(1);
  f.offline();
  await reopen();
  engine = f.newEngine();
  const saved = await engine.saveSupplierDraft(sale);
  expect(saved.localInvoiceNo).toMatch(/^OFF-[a-f0-9]{32}-000001$/);
  expect(engine.status().stock?.rows[0]).toMatchObject({ available: 0, used: 1 });
  await expect(engine.saveSupplierDraft(sale)).rejects.toThrow("حصة هذا الجهاز لا تكفي");
  await reopen();
  engine = f.newEngine();
  expect(engine.status().operations).toHaveLength(1);
  expect(engine.status().operations[0]).toMatchObject({
    reserved: true,
    localInvoiceNo: saved.localInvoiceNo,
    status: "pending",
  });
  expect((await fs.readFile(path.join(directory, "local.enc"))).toString()).not.toContain(
    "Private television",
  );
  f.online();
  f.loseSync();
  await engine.synchronize();
  expect(engine.status().pending).toBe(1);
  await engine.synchronize();
  expect(engine.status().operations[0]?.status).toBe("done");
  expect(f.receipts.size).toBe(1);
  const syncs = f.requests.filter((r) => r.path.endsWith("/sync/supplier-sale"));
  expect(syncs).toHaveLength(2);
  expect(syncs[0]?.body).toEqual(syncs[1]?.body);
  expect(engine.status().stock?.rows[0]?.available).toBe(0);
});
it("freezes before an uncertain return and never makes that quantity sellable after restart", async () => {
  const f = fixture();
  let engine = f.newEngine();
  await engine.manageStock("reserve", input);
  f.loseReturn();
  await expect(engine.manageStock("return")).rejects.toThrow();
  expect(engine.status().stock?.rows[0]).toMatchObject({ available: 0, frozen: true, used: 0 });
  await expect(engine.saveSupplierDraft(sale)).rejects.toThrow("حصة هذا الجهاز لا تكفي");
  await reopen();
  engine = f.newEngine();
  expect(engine.status().stock?.rows[0]?.frozen).toBe(true);
  await engine.manageStock("resume");
  expect(engine.status().stock?.rows[0]).toMatchObject({ available: 0, frozen: false, returned: 1 });
  const calls = f.requests.filter((r) => r.path.endsWith("/stock/return"));
  expect(calls).toHaveLength(2);
  expect(calls[0]?.body).toEqual(calls[1]?.body);
});
it("rolls back quota consumption and receipt counters when the disk checkpoint fails", async () => {
  const f = fixture();
  const engine = f.newEngine();
  await engine.manageStock("reserve", input);
  vi.spyOn(fs, "rename").mockRejectedValueOnce(new Error("disk full"));
  await expect(engine.saveSupplierDraft(sale)).rejects.toThrow("disk full");
  expect(engine.status().stock?.rows[0]).toMatchObject({ available: 1, used: 0 });
  expect(engine.status().operations).toEqual([]);
  expect((await engine.saveSupplierDraft(sale)).localInvoiceNo).toMatch(/000001$/);
});
it("rejects a different color and hides old grants when the employee changes", async () => {
  const f = fixture();
  const engine = f.newEngine();
  await engine.manageStock("reserve", input);
  await expect(
    engine.saveSupplierDraft({
      ...sale,
      items: [{ ...sale.items[0], product_id: 10, qty: 1, price: 300, variant_color: "أبيض" }],
    }),
  ).rejects.toThrow();
  expect(engine.status().stock?.rows[0]?.available).toBe(1);
  await engine.request({ method: "GET", path: "/api/v1/desktop/auth/session" }, async () => ({
    ok: true,
    status: 200,
    data: { ok: true, session: { ...session, user: { ...session.user, id: 2 } } },
  }));
  expect(engine.status().stock?.rows).toEqual([]);
});
it("rejects a mismatched server grant without importing a usable quantity", async () => {
  const f = fixture();
  const badSender = async (request: FinoraRequest): Promise<FinoraResponse> => {
    const response = await f.sender(request);
    if (request.path.endsWith("/stock/reserve") && response.ok) {
      const grant = stockGrantSchema.parse(response.data);
      return { ...response, data: { ...grant, employee_id: 99 } };
    }
    return response;
  };
  const engine = new OfflineEngine(store, "https://finora.test", badSender);
  await expect(engine.manageStock("reserve", input)).rejects.toThrow("لا تطابق");
  expect(engine.status().stock?.rows).toEqual([]);
  expect(engine.status().stock?.pendingRequest).toBe(true);
});
