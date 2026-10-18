import { randomBytes, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { OfflineDatabase } from "./offlineDatabase";
import { OfflineEngine } from "./offlineEngine";
import { sessionSchema } from "../../src/api/finora/schemas";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";

const SESSION = "/api/v1/desktop/auth/session";
const session = sessionSchema.parse({
  user: { id: 7, name: "Employee", username: "employee", role: "admin" },
  tenant: { id: 1, slug: "company-one", name: "Company", business_type: "general" },
  branch: { id: 1, name: "Branch" },
  roles: ["admin"],
  permissions: ["manage_customers", "finance.view", "finance.settings"],
  session_max_age_seconds: 604800,
});
const network: FinoraResponse = { ok: false, failure: "network" };
const success: FinoraResponse = { ok: true, status: 200, data: { success: true, data: { id: 8 } } };
let directory: string, store: OfflineDatabase, key: Buffer, file: string;
const wasm = path.resolve("node_modules/sql.js/dist/sql-wasm.wasm");
beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-customer-journal-test-"));
  file = path.join(directory, "business.enc");
  key = randomBytes(32);
  store = await OfflineDatabase.open(file, key, wasm);
});
afterEach(async () => {
  vi.restoreAllMocks();
  await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-customer-journal-test-")
  )
    throw Error("Unsafe cleanup");
  await fs.rm(directory, { recursive: true, force: true });
});
function request(suffix = "debts"): FinoraRequest {
  return {
    method: "POST",
    path: `/api/v1/desktop/customers/1/${suffix}`,
    body: {
      idempotency_key: randomUUID(),
      revision: "a".repeat(64),
      reason: "Private balance source",
      source_reference: "EXT-001",
      source_type: "opening",
      amount: 90000,
      count: 3,
      first_due_date: "2027-01-31",
      interval: "monthly",
    },
  };
}
async function fixture(initial = session) {
  let live = initial,
    verified: FinoraResponse | null = null,
    reply: FinoraResponse = network;
  const sender = vi.fn(async (r: FinoraRequest): Promise<FinoraResponse> =>
    r.path === SESSION ? (verified ?? { ok: true, status: 200, data: { ok: true, session: live } }) : reply,
  );
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  await engine.request({ method: "GET", path: SESSION });
  sender.mockClear();
  return {
    engine,
    sender,
    setLive: (s: typeof session) => {
      live = s;
    },
    setVerified: (r: FinoraResponse) => {
      verified = r;
    },
    setReply: (r: FinoraResponse) => {
      reply = r;
    },
  };
}

const stockSession = sessionSchema.parse({
  ...session,
  permissions: [
    ...session.permissions,
    "can_manage_inventory",
    "edit_current_stock",
    "edit_product",
    "finance.approve",
  ],
});
function stockRequest(suffix = "branch/transfers/3/send"): FinoraRequest {
  return {
    method: "POST",
    path: `/api/v1/desktop/stock-operations/${suffix}`,
    body: { operation_id: randomUUID(), revision: "b".repeat(64), reason: "Private stock source" },
  };
}
function stockKey(r: FinoraRequest) {
  return String((r.body as Record<string, unknown>).operation_id);
}
it("checkpoints a core storage command and refuses another phase until its outcome is resolved", async () => {
  const f = await fixture(stockSession),
    original = stockRequest("storage/transfers/3/send");
  await f.engine.request(original);
  expect(f.engine.stockCommands.list().items[0]?.request).toEqual(original);
  expect(await f.engine.request(stockRequest("storage/transfers/3/cancel"))).toMatchObject({
    ok: false,
    status: 409,
  });
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
  f.setLive(sessionSchema.parse({ ...stockSession, permissions: ["can_manage_inventory"] }));
  expect((await f.engine.stockCommands.retry(stockKey(original), f.sender)).response.ok).toBe(false);
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
});
it("never sends a core storage command if the encrypted checkpoint fails", async () => {
  const f = await fixture(stockSession);
  vi.spyOn(store, "write").mockRejectedValueOnce(Error("disk full"));
  await expect(f.engine.request(stockRequest("storage/locations/7"))).rejects.toThrow("disk full");
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
});
it.each(["storage/locations/0", "storage/transfers/3/approve", "storage/transfers/3/send/extra"])(
  "refuses an unsupported core storage command path %s",
  async (path) => {
    const f = await fixture(stockSession);
    expect((await f.engine.request(stockRequest(path))).ok).toBe(false);
    expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  },
);
it("stores stock separately from customer requests and restores the original stock UUID after restart", async () => {
  const f = await fixture(stockSession),
    original = stockRequest();
  await f.engine.request(request());
  await f.engine.request(original);
  expect(f.engine.customerCommands.list().items).toHaveLength(1);
  expect(f.engine.stockCommands.list().items[0]?.request).toEqual(original);
  const encrypted = await fs.readFile(file);
  expect(encrypted.includes(Buffer.from("Private stock source"))).toBe(false);
  await store.close();
  store = await OfflineDatabase.open(file, key, wasm);
  const sender = vi.fn(async (r: FinoraRequest): Promise<FinoraResponse> =>
    r.path === SESSION ? { ok: true, status: 200, data: { ok: true, session: stockSession } } : success,
  );
  const restarted = new OfflineEngine(store, "https://finora.test", sender);
  const recovered = await restarted.stockCommands.retry(stockKey(original), sender);
  if (!recovered.response.ok) throw Error("Stock recovery did not succeed");
  expect(recovered.request).toEqual(original);
  expect(sender.mock.calls.filter(([r]) => r.method === "POST").map(([r]) => r)).toEqual([original]);
  const confirmed = restarted.stockCommands.list().items[0];
  expect(confirmed?.state).toBe("confirmed");
  await restarted.stockCommands.acknowledge(
    stockKey(original),
    original.path,
    recovered.response.customerCommandScope ?? "",
  );
  expect(restarted.stockCommands.list().items).toEqual([]);
  expect(restarted.customerCommands.list().items).toHaveLength(1);
});
it("does not send stock when its encrypted checkpoint fails", async () => {
  const f = await fixture(stockSession);
  vi.spyOn(store, "write").mockRejectedValueOnce(Error("disk full"));
  await expect(f.engine.request(stockRequest())).rejects.toThrow("disk full");
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
});
it("makes send, receive and cancel share the unresolved transfer guard", async () => {
  const f = await fixture(stockSession);
  await f.engine.request(stockRequest());
  expect(await f.engine.request(stockRequest("branch/transfers/3/cancel"))).toMatchObject({
    ok: false,
    status: 409,
  });
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
});
it("revalidates stock permissions before replay", async () => {
  const f = await fixture(stockSession),
    original = stockRequest();
  await f.engine.request(original);
  f.setLive(sessionSchema.parse({ ...stockSession, permissions: ["can_manage_inventory"] }));
  const denied = await f.engine.stockCommands.retry(stockKey(original), f.sender);
  expect(denied.response.ok).toBe(false);
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
});
it("rejects stock replay after the live branch identity changes", async () => {
  const f = await fixture(stockSession),
    original = stockRequest();
  await f.engine.request(original);
  f.setLive(sessionSchema.parse({ ...stockSession, branch: { id: 2, name: "Other branch" } }));
  expect((await f.engine.stockCommands.retry(stockKey(original), f.sender)).response.ok).toBe(false);
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
});
it("does not replace the payload of an unresolved stock UUID", async () => {
  const f = await fixture(stockSession),
    original = stockRequest();
  await f.engine.request(original);
  const changed = {
    ...original,
    body: { ...(original.body as Record<string, unknown>), reason: "Changed source" },
  };
  expect(await f.engine.request(changed)).toMatchObject({ ok: false, status: 409 });
  expect(f.engine.stockCommands.list().items[0]?.request).toEqual(original);
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
});
it("keeps stock response rejection from signing the whole employee out", async () => {
  const f = await fixture(stockSession);
  f.setReply({
    ok: false,
    status: 403,
    failure: "http",
    data: { success: false, error: "Branch permission denied" },
  });
  expect((await f.engine.request(stockRequest())).ok).toBe(false);
  expect(f.engine.stockCommands.list().available).toBe(true);
});
it.each([
  "branch/transfers/3/send%2Fcancel",
  "warehouse/transfers",
  "branch/transfers/0/send",
  "branch/writeoffs/7/reverse",
])("rejects malformed or unauthorized stock paths without a POST: %s", async (suffix) => {
  const f = await fixture(stockSession);
  expect((await f.engine.request(stockRequest(suffix))).ok).toBe(false);
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
});
function keyOf(r: FinoraRequest): string {
  const body = r.body;
  if (!body || typeof body !== "object" || Array.isArray(body)) throw Error("No command");
  return String(body.idempotency_key);
}
function savedScope(): string {
  return String(store.one("SELECT scope FROM customer_commands LIMIT 1")?.scope);
}

it("checkpoints an encrypted request before transmission, survives database/process restart, and replays its exact UUID and fields", async () => {
  const f = await fixture(),
    original = request();
  f.sender.mockImplementation(async (r) => {
    if (r.path === SESSION) return { ok: true, status: 200, data: { ok: true, session } };
    expect(f.engine.customerCommands.list().items[0]?.request).toEqual(original);
    const bytes = await fs.readFile(file);
    expect(bytes.includes(Buffer.from("Private balance source"))).toBe(false);
    expect(bytes.includes(Buffer.from(keyOf(original)))).toBe(false);
    return network;
  });
  expect(await f.engine.request(original)).toEqual(network);
  await store.close();
  store = await OfflineDatabase.open(file, key, wasm);
  const sender = vi.fn(async (r: FinoraRequest): Promise<FinoraResponse> =>
    r.path === SESSION ? { ok: true, status: 200, data: { ok: true, session } } : success,
  );
  const restarted = new OfflineEngine(store, "https://finora.test", sender);
  const saved = restarted.customerCommands.list().items[0];
  expect(saved?.request).toEqual(original);
  await restarted.customerCommands.retry(keyOf(original), sender);
  expect(sender.mock.calls.filter(([r]) => r.method === "POST").map(([r]) => r)).toEqual([original]);
  expect(restarted.customerCommands.list().items[0]?.state).toBe("confirmed");
  await restarted.customerCommands.acknowledge(keyOf(original), original.path, savedScope());
  expect(restarted.customerCommands.list().items).toEqual([]);
});

it("does not transmit when the encrypted checkpoint fails", async () => {
  const f = await fixture();
  vi.spyOn(store, "write").mockRejectedValueOnce(Error("disk full"));
  await expect(f.engine.request(request())).rejects.toThrow("disk full");
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  expect(f.engine.customerCommands.list().items).toEqual([]);
});
it("keeps the original durable request if the server committed but the response checkpoint fails", async () => {
  const f = await fixture(),
    original = request();
  f.setReply(success);
  const write = store.write.bind(store);
  vi.spyOn(store, "write")
    .mockImplementationOnce(write)
    .mockImplementationOnce(write)
    .mockRejectedValueOnce(Error("disk full"));
  await expect(f.engine.request(original)).rejects.toThrow("disk full");
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
  expect(f.engine.customerCommands.list().items[0]?.request).toEqual(original);
  expect(f.engine.customerCommands.list().items[0]?.state).toBe("uncertain");
});
it.each(["debts", "invoices/11/schedule", "plans/3/repartition", "plans/3/schedule"])(
  "blocks a different UUID for the same unresolved source (%s)",
  async (suffix) => {
    const f = await fixture(),
      original = request(suffix);
    await f.engine.request(original);
    const changed = request(suffix);
    expect(await f.engine.request(changed)).toMatchObject({ ok: false, status: 409 });
    expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
    expect(f.engine.customerCommands.list().items).toHaveLength(1);
  },
);
it("makes manual editing and repartitioning share one source guard", async () => {
  const f = await fixture();
  await f.engine.request(request("plans/3/repartition"));
  expect(await f.engine.request(request("plans/3/schedule"))).toMatchObject({ status: 409 });
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(1);
});
it("rejects changed fields under the original UUID, but permits an unchanged ordered-object replay", async () => {
  const f = await fixture(),
    original = request();
  await f.engine.request(original);
  const data = original.body as Record<string, string | number>;
  expect(await f.engine.request({ ...original, body: { ...data, amount: 100000 } })).toMatchObject({
    status: 409,
  });
  const reordered = Object.fromEntries(Object.entries(data).reverse());
  expect(await f.engine.request({ ...original, body: reordered })).toEqual(network);
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(2);
});
it.each([400, 404, 409, 422])(
  "clears a first explicit business rejection (%s), permitting a corrected fresh command",
  async (status) => {
    const f = await fixture();
    f.setReply({ ok: false, failure: "http", status, data: { error: "Rejected" } });
    await f.engine.request(request());
    expect(f.engine.customerCommands.list().items).toHaveLength(0);
  },
);
it.each([403, 409, 429, 500])(
  "retains an uncertain original after a rejected replay (%s)",
  async (status) => {
    const f = await fixture(),
      original = request();
    await f.engine.request(original);
    f.setReply({ ok: false, failure: "http", status, data: { error: "Rejected" } });
    await f.engine.request(original);
    if (status === 403) await f.engine.request({ method: "GET", path: SESSION });
    expect(f.engine.customerCommands.list().items).toHaveLength(1);
    await f.engine.customerCommands.acknowledge(keyOf(original), original.path, savedScope());
    expect(f.engine.customerCommands.list().items).toHaveLength(1);
  },
);
it("requires a successful response and a matching path to acknowledge; malformed success stays reviewable", async () => {
  const f = await fixture(),
    original = request();
  f.setReply({ ok: true, status: 200, data: { success: true, data: { id: "not-an-id" } } });
  await f.engine.request(original);
  await f.engine.customerCommands.acknowledge(keyOf(original), original.path, savedScope());
  expect(f.engine.customerCommands.list().items).toHaveLength(1);
  f.setReply(success);
  await f.engine.request(original);
  await f.engine.customerCommands.acknowledge(
    keyOf(original),
    "/api/v1/desktop/customers/2/debts",
    savedScope(),
  );
  expect(f.engine.customerCommands.list().items).toHaveLength(1);
});
it.each(["company", "tenant-id", "employee", "branch", "scope"])(
  "rejects replay into a different live %s",
  async (kind) => {
    const f = await fixture(),
      original = request();
    await f.engine.request(original);
    f.sender.mockClear();
    f.setLive({
      ...session,
      tenant: {
        ...session.tenant,
        ...(kind === "company" ? { slug: "company-two" } : {}),
        ...(kind === "tenant-id" ? { id: 2 } : {}),
      },
      user: { ...session.user, ...(kind === "employee" ? { id: 8 } : {}) },
      branch: { id: 1, name: "Branch", ...(kind === "branch" ? { id: 2 } : {}) },
      ...(kind === "scope" ? { branch_scope: "all" } : {}),
    });
    expect(await f.engine.request(original)).toMatchObject({ ok: false, failure: "unauthenticated" });
    expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
    expect(Number(store.one("SELECT COUNT(*) AS n FROM customer_commands")?.n)).toBe(1);
  },
);
it("hides requests from another server and on signout without deleting them", async () => {
  const f = await fixture();
  await f.engine.request(request());
  expect(new OfflineEngine(store, "https://other.test", f.sender).customerCommands.list()).toEqual({
    available: false,
    items: [],
  });
  await f.engine.deactivate();
  expect(f.engine.customerCommands.list().items).toHaveLength(0);
  await f.engine.request({ method: "GET", path: SESSION });
  expect(f.engine.customerCommands.list().items).toHaveLength(1);
});
it("fresh permission revocation and an offline cached session cannot authorize replay", async () => {
  const f = await fixture(),
    original = request();
  await f.engine.request(original);
  f.sender.mockClear();
  f.setLive({ ...session, permissions: ["manage_customers"] });
  expect(await f.engine.request(original)).toMatchObject({ status: 403 });
  f.setLive(session);
  await f.engine.request({ method: "GET", path: SESSION });
  f.sender.mockClear();
  f.setVerified({ ok: true, status: 200, source: "offline", data: { ok: true, session } });
  expect(await f.engine.request(original)).toEqual(network);
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
});
it("serializes concurrent identical writes and preserves a confirmed result until acknowledgement", async () => {
  const f = await fixture(),
    original = request();
  f.setReply(success);
  await Promise.all([f.engine.request(original), f.engine.request(original)]);
  expect(f.engine.customerCommands.list().items).toHaveLength(1);
  expect(f.engine.customerCommands.list().items[0]?.state).toBe("confirmed");
});
it("does not add customer requests to automatic offline synchronization", async () => {
  const f = await fixture();
  await f.engine.request(request());
  f.sender.mockClear();
  await f.engine.synchronize();
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  expect(f.engine.customerCommands.list().items).toHaveLength(1);
});

it("keeps pending profiles separate by update target and blocks a second uncertain customer creation", async () => {
  const f = await fixture();
  const make = (operation: string, id?: number): FinoraRequest => ({
    method: "POST",
    path: "/api/v1/desktop/customers/commands",
    body: {
      operation,
      ...(id ? { id } : {}),
      idempotency_key: randomUUID(),
      data: { name: "Private profile" },
    },
  });
  await f.engine.request(make("create"));
  expect(await f.engine.request(make("create"))).toMatchObject({ status: 409 });
  await f.engine.request(make("update", 1));
  await f.engine.request(make("update", 2));
  expect(await f.engine.request(make("update", 1))).toMatchObject({ status: 409 });
  expect(f.engine.customerCommands.list().items).toHaveLength(3);
});
it("an old success cannot acknowledge a same-UUID request in another company", async () => {
  const f = await fixture(),
    original = request();
  f.setReply(success);
  await f.engine.request(original);
  const oldScope = savedScope();
  f.setLive({ ...session, tenant: { ...session.tenant, slug: "company-two", id: 2 } });
  await f.engine.request({ method: "GET", path: SESSION });
  expect(f.engine.customerCommands.list().items).toHaveLength(0);
  await f.engine.request(original);
  await expect(
    f.engine.customerCommands.acknowledge(keyOf(original), original.path, oldScope),
  ).rejects.toThrow("الجلسة");
  expect(Number(store.one("SELECT COUNT(*) AS n FROM customer_commands")?.n)).toBe(2);
});
it.each([
  "/api/v1/desktop/customers/1/unknown",
  "/api/v1/desktop/%63ustomers/1/debts",
  "/api/v1/desktop/customers/%31/debts",
])("refuses unknown or encoded customer writes before transmission (%s)", async (path) => {
  const f = await fixture();
  expect(await f.engine.request({ ...request(), path })).toMatchObject({ status: 400 });
  expect(f.sender).not.toHaveBeenCalled();
});
it("refuses an invalid UUID before any transmission", async () => {
  const f = await fixture();
  const original = request();
  expect(
    await f.engine.request({
      ...original,
      body: { ...(original.body as Record<string, string>), idempotency_key: "not-a-uuid" },
    }),
  ).toMatchObject({ status: 400 });
  expect(f.sender).not.toHaveBeenCalled();
  expect(f.engine.customerCommands.list().items).toHaveLength(0);
});
