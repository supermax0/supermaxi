import { randomBytes, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { PosSale } from "../../shared/offline";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
import { OfflineDatabase } from "./offlineDatabase";
import { OfflineEngine } from "./offlineEngine";
import { receiptHtml } from "./posReceipt";

const session = {
  user: { id: 1, name: "Cashier", username: "cashier", role: "cashier" },
  tenant: { id: 1, slug: "tenant", name: "Private company", business_type: "general" },
  branch: { id: 1, name: "Main" },
  roles: ["cashier"],
  permissions: ["view_pos", "pay_orders", "print_pos_invoice", "can_manage_suppliers"],
  session_max_age_seconds: 604800,
  offline_pos_enabled: true,
};
let directory: string, store: OfflineDatabase, key: Buffer;
const wasm = path.resolve("node_modules/sql.js/dist/sql-wasm.wasm");
beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-pos-test-"));
  key = randomBytes(32);
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
});
afterEach(async () => {
  vi.restoreAllMocks();
  await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-pos-test-")
  )
    throw new Error("Unsafe cleanup");
  await fs.rm(directory, { recursive: true, force: true });
});
function fixture() {
  let online = true,
    loseSync = false;
  const receipts = new Map<string, unknown>(),
    requests: FinoraRequest[] = [];
  const sender = vi.fn(async (request: FinoraRequest): Promise<FinoraResponse> => {
    requests.push(request);
    if (!online) return { ok: false, failure: "network" };
    if (request.path === "/api/v1/desktop/auth/session")
      return { ok: true, status: 200, data: { ok: true, session } };
    let data: unknown;
    if (request.path === "/pos/api/products")
      data = {
        rows: [
          {
            id: 10,
            name: "Television",
            price: 300,
            has_colors: true,
            colors: [{ name: "أسود", sale_price: 300 }],
          },
        ],
      };
    else if (request.path === "/suppliers/api/sale-products")
      data = [{ id: 10, quantity: 2, colors: [{ name: "أسود", qty: 2 }] }];
    else if (request.path === "/pos/search-customer")
      data = [{ id: 7, name: "Customer", blacklisted: false }];
    else if (request.path === "/orders/payment-accounts")
      data = {
        accounts: [
          { id: 4, type: "cash", branch_id: 1 },
          { id: 5, type: "bank", branch_id: 1 },
        ],
      };
    else if (request.path.endsWith("/stock/reserve")) {
      const body = request.body as { id: string; device_id: string };
      data = {
        success: true,
        id: body.id,
        device_id: body.device_id,
        employee_id: 1,
        branch_id: 1,
        allocations: [
          {
            id: randomUUID(),
            product_id: 10,
            name: "Television",
            variant_color: "أسود",
            quantity: 1,
            sale_price: 300,
          },
        ],
      };
    } else if (request.path.endsWith("/sync/pos-sale")) {
      const body = request.body as { operation_id: string };
      if (!receipts.has(body.operation_id))
        receipts.set(body.operation_id, { success: true, invoice_no: "100", invoice_id: 100 });
      data = receipts.get(body.operation_id);
      if (loseSync) {
        loseSync = false;
        return { ok: false, failure: "network" };
      }
    } else throw new Error(`Unexpected ${request.path}`);
    return { ok: true, status: 200, data };
  });
  const engine = () => new OfflineEngine(store, "https://finora.test", sender);
  return {
    engine,
    sender,
    requests,
    receipts,
    offline: () => {
      online = false;
    },
    online: () => {
      online = true;
    },
    loseSync: () => {
      loseSync = true;
    },
  };
}
const input: PosSale = {
  kind: "pos",
  customerId: 7,
  customerName: "Customer",
  items: [{ product_id: 10, qty: 1, price: 300, variant_color: "أسود" }],
  discount: 20,
  total: 280,
  payment: "cash",
  accountId: 4,
};
async function prepare(engine: OfflineEngine) {
  await engine.request({ method: "GET", path: "/api/v1/desktop/auth/session" });
  for (const path of ["/pos/api/products", "/pos/search-customer", "/orders/payment-accounts"])
    await engine.request({ method: "GET", path });
  await engine.manageStock("reserve", [{ product_id: 10, qty: 1, variant_color: "أسود" }]);
}

it.each(["cash", "bank", "credit"] as const)(
  "%s checkout survives restart, consumes the last piece once and replays an uncertain server acknowledgement",
  async (payment) => {
    const f = fixture();
    let engine = f.engine();
    await prepare(engine);
    f.offline();
    const id = randomUUID(),
      sale = { ...input, payment, accountId: payment === "cash" ? 4 : payment === "bank" ? 5 : null };
    const saved = await engine.savePosSale(id, sale);
    expect(saved.localInvoiceNo).toMatch(/^OFF-[a-f0-9]{32}-000001$/);
    expect(await engine.savePosSale(id, sale)).toEqual(saved);
    await expect(engine.savePosSale(randomUUID(), sale)).rejects.toThrow("حصة");
    await store.close();
    store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
    engine = f.engine();
    expect(await engine.savePosSale(id, sale)).toEqual(saved);
    const receipt = await engine.posReceipt(id);
    expect(receipt.sale.payment).toBe(payment);
    expect(receiptHtml(receipt)).toContain("بانتظار المزامنة");
    f.online();
    f.loseSync();
    await engine.synchronize();
    expect(engine.status().pending).toBe(1);
    await engine.synchronize();
    expect(engine.status().operations[0]?.status).toBe("done");
    expect(f.receipts.size).toBe(1);
    const sent = f.requests.filter((r) => r.path.endsWith("/sync/pos-sale"));
    expect(sent).toHaveLength(2);
    expect(sent[0]?.body).toEqual(sent[1]?.body);
    expect(sent[0]?.body).toMatchObject({ operation_id: id, sale, reservations: [{ qty: 1 }] });
    expect((await engine.posReceipt(id)).invoice).toBe("100");
  },
);

it("failed disk checkpoint leaves quota, receipt counter and checkout unchanged", async () => {
  const f = fixture(),
    engine = f.engine();
  await prepare(engine);
  vi.spyOn(fs, "rename").mockRejectedValueOnce(new Error("disk failure"));
  await expect(engine.savePosSale(randomUUID(), input)).rejects.toThrow("disk failure");
  expect(engine.status().stock?.rows[0]?.available).toBe(1);
  expect(engine.status().operations).toHaveLength(0);
  expect((await engine.savePosSale(randomUUID(), input)).localInvoiceNo).toMatch(/000001$/);
});

it("supplier drafts account for pending POS items and reserved sales share the same device pool", async () => {
  const f = fixture(),
    engine = f.engine();
  await prepare(engine);
  await engine.request({ method: "GET", path: "/suppliers/api/sale-products" });
  f.offline();
  await engine.savePosSale(randomUUID(), input);
  const supplier = { supplierId: 7, supplierName: "Supplier", items: input.items, note: "" };
  await expect(engine.saveSupplierDraft({ ...supplier, stockMode: "reserved" })).rejects.toThrow("حصة");
  await engine.saveSupplierDraft(supplier);
  expect(engine.status().operations).toHaveLength(2);
  expect(engine.status().stock?.rows[0]?.available).toBe(0);
  await expect(engine.saveSupplierDraft(supplier)).rejects.toThrow("آخر مخزون");
});

it("refuses final local POS checkout when the server has not advertised support", async () => {
  const f = fixture();
  const sender = async (request: FinoraRequest): Promise<FinoraResponse> =>
    request.path === "/api/v1/desktop/auth/session"
      ? { ok: true, status: 200, data: { ok: true, session: { ...session, offline_pos_enabled: false } } }
      : f.sender(request);
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  await prepare(engine);
  await expect(engine.savePosSale(randomUUID(), input)).rejects.toThrow("حدّث السيرفر");
  expect(engine.status().operations).toHaveLength(0);
  expect(engine.status().stock?.rows[0]?.available).toBe(1);
});

it("rejects unknown customers, altered prices and wrong payment branches before taking quota", async () => {
  const f = fixture(),
    engine = f.engine();
  await prepare(engine);
  await expect(engine.savePosSale(randomUUID(), { ...input, customerId: 8 })).rejects.toThrow("زبون");
  await expect(
    engine.savePosSale(randomUUID(), {
      ...input,
      items: [{ product_id: 10, qty: 1, variant_color: "أسود", price: 500 }],
      total: 480,
    }),
  ).rejects.toThrow("سعر");
  await expect(engine.savePosSale(randomUUID(), { ...input, accountId: 6 })).rejects.toThrow("حساب");
  expect(engine.status().stock?.rows[0]?.available).toBe(1);
  const saved = await engine.savePosSale(randomUUID(), input);
  await expect(engine.savePosSale(saved.id, { ...input, discount: 10, total: 290 })).rejects.toThrow(
    "بنفس المعرّف",
  );
});

it("escapes stored customer, product and colour strings in the printable receipt", () => {
  const html = receiptHtml({
    number: "OFF-1",
    sale: {
      ...input,
      customerName: "<script>alert(1)</script>",
      items: [{ product_id: 10, qty: 1, price: 300, variant_color: "<img src=x onerror=alert(1)>" }],
    },
    names: ['<iframe src="https://evil.test">'],
    created: 1,
    invoice: null,
  });
  expect(html).not.toContain("<script>");
  expect(html).not.toContain("<iframe");
  expect(html).not.toContain("<img");
  expect(html).toContain("&lt;script&gt;");
  expect(html).toContain("default-src 'none'");
});
