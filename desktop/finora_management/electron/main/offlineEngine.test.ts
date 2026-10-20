import { randomBytes, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
import { OfflineDatabase } from "./offlineDatabase";
import { OfflineEngine } from "./offlineEngine";

const SESSION = "/api/v1/desktop/auth/session";
const READ: FinoraRequest = { method: "GET", path: "/suppliers/api/sale-products", query: { q: "TV" } };
const session = {
  user: { id: 1, name: "Private employee", username: "employee", role: "admin" },
  tenant: { id: 1, slug: "tenant-one", name: "Private company", business_type: "general" },
  branch: { id: 1, name: "Main" },
  roles: ["admin"],
  permissions: ["can_manage_suppliers"],
  session_max_age_seconds: 604800,
};
const product = {
  id: 10,
  name: "Private television",
  sku: "TV",
  barcode: "123",
  sale_price: 300,
  quantity: 1,
  has_colors: false,
  colors: [],
};
const draft = {
  supplierId: 7,
  supplierName: "Private supplier",
  items: [{ product_id: 10, qty: 1, price: 300 }],
  note: "Private note",
};
let directory: string;
let store: OfflineDatabase;
let key: Buffer;
const wasm = path.resolve("node_modules/sql.js/dist/sql-wasm.wasm");
const unavailable: FinoraResponse = { ok: false, failure: "network" };

beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-offline-test-"));
  key = randomBytes(32);
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
});
afterEach(async () => {
  vi.restoreAllMocks();
  await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-offline-test-")
  )
    throw new Error("Unsafe test cleanup path");
  await fs.rm(directory, { recursive: true, force: true });
});
function fixture() {
  let online = true;
  const sender = vi.fn(async (r: FinoraRequest): Promise<FinoraResponse> => {
    if (!online) return unavailable;
    return { ok: true, status: 200, data: r.path === SESSION ? { ok: true, session } : [product] };
  });
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  return {
    engine,
    sender,
    disconnect: () => {
      online = false;
    },
  };
}

it.each(["sales", "receivables", "activity"])(
  "caches workspace %s in the existing encrypted, permission-scoped offline store",
  async (part) => {
    const { engine, sender, disconnect } = fixture();
    await engine.request({ method: "GET", path: SESSION });
    const request: FinoraRequest = { method: "GET", path: `/api/v1/desktop/workspace/${part}` };
    const first = await engine.request(request);
    disconnect();
    const cached = await engine.request(request);
    expect(cached.ok).toBe(true);
    expect(cached).toMatchObject({ source: "offline", data: first.ok ? first.data : null });
    expect(
      (await fs.readFile(path.join(directory, "local.enc"))).includes(Buffer.from("Private television")),
    ).toBe(false);
    expect(sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(0);
  },
);

it.each(["session-review", "late-error", "late-invalid"])(
  "keeps a confirmed HR approval done during concurrent synchronization (%s)",
  async (race) => {
    function deferred<T>() {
      let resolve!: (value: T) => void;
      const promise = new Promise<T>((done) => {
        resolve = done;
      });
      return { promise, resolve };
    }
    const checked: FinoraResponse = {
      ok: true,
      status: 200,
      data: { ok: true, session: { ...session, permissions: ["hr.view", "hr.attendance.approve"] } },
    };
    const live = deferred<FinoraResponse>(),
      review = deferred<FinoraResponse>(),
      late = deferred<FinoraResponse>();
    const sent = deferred<boolean>(),
      reviewed = deferred<boolean>(),
      replayed = deferred<boolean>();
    let sessionCalls = 0,
      posts = 0;
    const sender = vi.fn(async (r: FinoraRequest): Promise<FinoraResponse> => {
      if (r.path === SESSION) {
        if (++sessionCalls === 2) {
          reviewed.resolve(true);
          if (race === "session-review") return review.promise;
        }
        return checked;
      }
      if (r.path === "/hr/api/commands") {
        if (++posts === 1) {
          sent.resolve(true);
          return live.promise;
        }
        replayed.resolve(true);
        return race === "session-review" ? unavailable : late.promise;
      }
      return unavailable;
    });
    const engine = new OfflineEngine(store, "https://finora.test", sender);
    await engine.request({ method: "GET", path: SESSION });
    const id = randomUUID();
    const request = engine.request({
      method: "POST",
      path: "/hr/api/commands",
      body: {
        id,
        action: "attendance.correction_decide",
        payload: { correction_id: 1, version: 1, status: "approved", reason: "reviewed" },
      },
    });
    await sent.promise;
    const background = engine.synchronize();
    if (race === "session-review") await reviewed.promise;
    else await replayed.promise;
    live.resolve({ ok: true, status: 200, data: { success: true, id: 1, version: 2 } });
    expect(await request).toMatchObject({ ok: true });
    if (race === "session-review") review.resolve(checked);
    else
      late.resolve(
        race === "late-invalid" ? { ok: true, status: 200, data: { success: true } } : unavailable,
      );
    await background;
    expect(engine.status().operations.find((row) => row.id === id)?.status).toBe("done");
    expect(posts).toBe(race === "session-review" ? 1 : 2);
  },
);

it("keeps finance drafts private, durable and non-posting across offline retries", async () => {
  let online = true;
  const active = { ...session, permissions: ["finance.view", "finance.create"] };
  const metadata = {
    success: true,
    data: {
      categories: [{ id: "expense", kind: "payment", label: "مصروف", party_type: "other" }],
      accounts: [{ id: 1, name: "الصندوق", branch_id: 1 }],
    },
  };
  const sender = vi.fn(async (r: FinoraRequest): Promise<FinoraResponse> => {
    if (!online) return unavailable;
    if (r.path === SESSION) return { ok: true, status: 200, data: { ok: true, session: active } };
    if (r.path === "/api/finance/meta") return { ok: true, status: 200, data: metadata };
    return {
      ok: true,
      status: 200,
      data: { success: true, data: { id: 88, number: "PY-000088", status: "draft" } },
    };
  });
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  await engine.request({ method: "GET", path: SESSION });
  await engine.request({ method: "GET", path: "/api/finance/meta" });
  online = false;
  const command: FinoraRequest = {
    method: "POST",
    path: "/api/finance/commands",
    body: {
      operation: "voucher.create",
      idempotency_key: "finance-local-1234",
      category: "expense",
      amount: 200000,
      treasury_account_id: 1,
      branch_id: 1,
      intent: "draft",
    },
  };
  const result = await engine.request(command);
  expect(result.ok && result.data).toMatchObject({
    success: true,
    data: { status: "local_pending", amount: 200000 },
  });
  await engine.request(command);
  expect(engine.status().operations.filter((o) => o.kind === "finance")).toHaveLength(1);
  const posted = await engine.request({
    ...command,
    body: { ...(command.body as object), intent: "post", idempotency_key: "finance-post-1234" },
  });
  expect(posted).toMatchObject({ ok: false, failure: "network" });
  online = true;
  await engine.synchronize();
  expect(engine.status().operations.find((o) => o.kind === "finance")).toMatchObject({
    status: "done",
    invoiceNo: "PY-000088",
  });
  const transmitted = sender.mock.calls
    .filter(([r]) => r.path === "/api/finance/commands" && online)
    .map(([r]) => r);
  expect(transmitted.at(-1)?.body).toMatchObject({ intent: "draft", idempotency_key: "finance-local-1234" });
  const other = new OfflineEngine(store, "https://different.test", sender);
  expect(other.status().operations).toEqual([]);
});

it("replays offline check-in then its linked checkout in durable creation order", async () => {
  let online = true;
  const active = { ...session, permissions: ["hr.view", "hr.attendance.record"] };
  const sender = vi.fn(async (r: FinoraRequest): Promise<FinoraResponse> => {
    if (!online) return unavailable;
    if (r.path === SESSION) return { ok: true, status: 200, data: { ok: true, session: active } };
    return { ok: true, status: 200, data: { success: true, id: 22, version: 1 } };
  });
  const engine = new OfflineEngine(store, "https://finora.test", sender, () =>
    Date.parse("2026-10-10T10:00:00Z"),
  );
  await engine.request({ method: "GET", path: SESSION });
  online = false;
  await engine.request({ method: "GET", path: SESSION });
  const first = {
    id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
    action: "attendance.record",
    payload: { person_id: 7, event: "check_in", occurred_at: "2026-10-10T05:00:00Z" },
  };
  const second = {
    id: "00000000-0000-4000-8000-000000000001",
    action: "attendance.record",
    payload: { person_id: 7, event: "check_out", occurred_at: "2026-10-10T09:00:00Z" },
  };
  for (const body of [first, second])
    expect(await engine.request({ method: "POST", path: "/hr/api/commands", body })).toMatchObject({
      ok: true,
      source: "offline",
    });
  await engine.request({
    method: "POST",
    path: "/hr/api/commands",
    body: {
      ...second,
      id: crypto.randomUUID(),
      payload: { ...second.payload, occurred_at: "2026-10-10T09:01:00Z" },
    },
  });
  expect(engine.status().pending).toBe(2);
  online = true;
  await engine.synchronize();
  const calls = sender.mock.calls
    .map(([r]) => r)
    .filter((r) => r.method === "POST")
    .map((r) => r.body);
  expect(calls).toEqual([
    first,
    { ...second, payload: { ...second.payload, check_in_command_id: first.id } },
  ]);
  expect(engine.status().pending).toBe(0);
});

it("does not replay an HR command acknowledged while the background batch verifies its session", async () => {
  const active = { ...session, permissions: ["hr.view", "hr.attendance.record"] };
  let releaseCommand!: () => void;
  let releaseVerification!: () => void;
  let commandStarted!: () => void;
  let verificationStarted!: () => void;
  const commandGate = new Promise<void>((resolve) => {
    releaseCommand = resolve;
  });
  const verificationGate = new Promise<void>((resolve) => {
    releaseVerification = resolve;
  });
  const commandReady = new Promise<void>((resolve) => {
    commandStarted = resolve;
  });
  const verificationReady = new Promise<void>((resolve) => {
    verificationStarted = resolve;
  });
  let verifyBatch = false;
  const sender = vi.fn(async (request: FinoraRequest): Promise<FinoraResponse> => {
    if (request.path === SESSION) {
      if (verifyBatch) {
        verificationStarted();
        await verificationGate;
      }
      return { ok: true, status: 200, data: { ok: true, session: active } };
    }
    commandStarted();
    await commandGate;
    return { ok: true, status: 200, data: { success: true, id: 123, version: 1 } };
  });
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  await engine.request({ method: "GET", path: SESSION });
  const command = engine.request({
    method: "POST",
    path: "/hr/api/commands",
    body: {
      id: crypto.randomUUID(),
      action: "attendance.record",
      payload: { person_id: 7, event: "check_in", occurred_at: "2026-10-10T05:00:00Z" },
    },
  });
  await commandReady;
  verifyBatch = true;
  const background = engine.synchronize();
  await verificationReady;
  releaseCommand();
  const acknowledged = await command;
  releaseVerification();
  await background;
  expect(acknowledged).toMatchObject({ ok: true, data: { success: true, id: 123 } });
  expect(sender.mock.calls.filter(([request]) => request.method === "POST")).toHaveLength(1);
  expect(engine.status().operations[0]).toMatchObject({ kind: "hr", status: "done" });
});

it("coalesces never-transmitted personal edits but preserves the UUID and payload of an uncertain send", async () => {
  let online = true;
  const active = { ...session, permissions: ["hr.view", "hr.employees.edit"] };
  const sender = async (r: FinoraRequest): Promise<FinoraResponse> =>
    online && r.path === SESSION
      ? { ok: true, status: 200, data: { ok: true, session: active } }
      : unavailable;
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  await engine.request({ method: "GET", path: SESSION });
  online = false;
  await engine.request({ method: "GET", path: SESSION });
  const id = crypto.randomUUID();
  const request = (commandId: string, payload: Record<string, unknown>): FinoraRequest => ({
    method: "POST",
    path: "/hr/api/commands",
    body: { id: commandId, action: "employee.update", payload: { person_id: 7, version: 1, ...payload } },
  });
  await engine.request(request(id, { phone: "0771" }));
  await engine.request(request(crypto.randomUUID(), { address: "بغداد" }));
  expect(engine.status().pending).toBe(1);
  const before = JSON.parse(String(store.one("SELECT payload FROM operations WHERE id=?", [id])?.payload));
  expect(before.command).toMatchObject({ id, payload: { phone: "0771", address: "بغداد" } });
  await expect(engine.request(request(crypto.randomUUID(), { version: 2, phone: "0773" }))).rejects.toThrow(
    "نسخة الموظف",
  );
  online = true;
  await engine.synchronize();
  online = false;
  await engine.request({ method: "GET", path: SESSION });
  await expect(engine.request(request(crypto.randomUUID(), { phone: "0772" }))).rejects.toThrow(
    "بانتظار تأكيد",
  );
  expect(
    JSON.parse(String(store.one("SELECT payload FROM operations WHERE id=?", [id])?.payload)).command,
  ).toEqual(before.command);
});

it.each([{ id: 22 }, { success: true, id: 0 }, { success: true, id: 1.5 }])(
  "keeps malformed financial acknowledgements %j unresolved and blocks a different second payment",
  async (receipt) => {
    const active = { ...session, permissions: ["hr.view", "hr.payroll.pay"] };
    const sender = async (r: FinoraRequest): Promise<FinoraResponse> => ({
      ok: true,
      status: 200,
      data: r.path === SESSION ? { ok: true, session: active } : receipt,
    });
    const engine = new OfflineEngine(store, "https://finora.test", sender);
    await engine.request({ method: "GET", path: SESSION });
    const pay = (amount: number): FinoraRequest => ({
      method: "POST",
      path: "/hr/api/commands",
      body: {
        id: crypto.randomUUID(),
        action: "payroll.pay",
        payload: { item_id: 8, amount, treasury_account_id: 1 },
      },
    });
    expect(await engine.request(pay(1000))).toMatchObject({ ok: false, failure: "invalid_response" });
    expect(engine.status().pending).toBe(1);
    const operation = engine.status().operations[0];
    if (!operation) throw new Error("Expected unresolved payment");
    await expect(engine.discardHR(operation.id)).rejects.toThrow("غير المؤكد");
    await expect(engine.request(pay(2000))).rejects.toThrow("دفعة لهذا الاستحقاق");
  },
);

it("lets a user discard a definitively rejected personal edit without replaying or confirming it", async () => {
  const active = { ...session, permissions: ["hr.view", "hr.employees.edit"] };
  const sender = async (r: FinoraRequest): Promise<FinoraResponse> =>
    r.path === SESSION
      ? { ok: true, status: 200, data: { ok: true, session: active } }
      : { ok: false, failure: "http", status: 409, data: { error: "تغيرت البيانات" } };
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  await engine.request({ method: "GET", path: SESSION });
  const id = crypto.randomUUID();
  await engine.request({
    method: "POST",
    path: "/hr/api/commands",
    body: { id, action: "employee.update", payload: { person_id: 7, version: 1, phone: "0771" } },
  });
  expect(engine.status().operations[0]).toMatchObject({ status: "conflict", canDiscard: true });
  const next = await engine.discardHR(id);
  expect(next.conflicts).toBe(0);
  expect(next.operations[0]).toMatchObject({ status: "cancelled", invoiceNo: null, canDiscard: false });
});

it("stores HR attendance durably, replays one command and keeps salary approval central", async () => {
  let connected = true;
  const hrSession = {
    ...session,
    permissions: [...session.permissions, "hr.view", "hr.attendance.record", "hr.payroll.pay"],
  };
  const sender = vi.fn(async (request: FinoraRequest): Promise<FinoraResponse> => {
    if (!connected) return unavailable;
    if (request.path === SESSION) return { ok: true, status: 200, data: { ok: true, session: hrSession } };
    if (request.method === "POST") return { ok: true, status: 200, data: { success: true, id: 123 } };
    return { ok: true, status: 200, data: { rows: [], total: 0, page: 1, page_size: 25, total_pages: 1 } };
  });
  const engine = new OfflineEngine(store, "https://finora.test", sender);
  await engine.request({ method: "GET", path: SESSION });
  connected = false;
  const attendance: FinoraRequest = {
    method: "POST",
    path: "/hr/api/commands",
    body: {
      id: crypto.randomUUID(),
      action: "attendance.record",
      payload: { person_id: 7, event: "check_in", occurred_at: new Date().toISOString() },
    },
  };
  const queued = await engine.request(attendance);
  expect(queued).toMatchObject({ ok: true, source: "offline", data: { pending: true } });
  expect(engine.status().operations[0]).toMatchObject({ kind: "hr", status: "pending" });
  const salary = await engine.request({
    method: "POST",
    path: "/hr/api/commands",
    body: {
      id: crypto.randomUUID(),
      action: "payroll.pay",
      payload: { item_id: 9, amount: 1000, treasury_account_id: 1 },
    },
  });
  expect(salary.ok).toBe(false);
  expect(engine.status().pending).toBe(1);
  // A new dialog's request UUID still resumes an uncertain identical operation.
  const retry = await engine.request({
    ...attendance,
    body: { ...(attendance.body as Record<string, never>), id: crypto.randomUUID() },
  });
  expect(retry.ok).toBe(true);
  expect(engine.status().pending).toBe(1);
  connected = true;
  await engine.synchronize();
  expect(engine.status().operations[0]).toMatchObject({ kind: "hr", status: "done" });
  expect(
    sender.mock.calls.filter(
      ([r]) => r.method === "POST" && (r.body as { action?: string }).action === "attendance.record",
    ),
  ).toHaveLength(2);
  expect(
    sender.mock.calls.filter(
      ([r]) => r.method === "POST" && (r.body as { action?: string }).action === "payroll.pay",
    ),
  ).toHaveLength(0);
});

it("encrypts cached data and restores the authorized offline session after restart", async () => {
  const f = fixture();
  await f.engine.request({ method: "GET", path: SESSION });
  await f.engine.request(READ);
  const file = await fs.readFile(path.join(directory, "local.enc"));
  expect(file.toString()).not.toContain("Private");
  expect(file.toString()).not.toContain("SQLite format");
  await store.close();
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
  const restored = new OfflineEngine(store, "https://finora.test", async () => unavailable);
  expect(await restored.request({ method: "GET", path: SESSION })).toMatchObject({
    ok: true,
    source: "offline",
  });
  expect(await restored.request(READ)).toMatchObject({ ok: true, source: "offline", data: [product] });
  const wrongServer = new OfflineEngine(store, "https://another.test", async () => unavailable);
  expect((await wrongServer.request(READ)).ok).toBe(false);
});

it("does not grant another user old cached data and disables offline access on failed login", async () => {
  const f = fixture();
  await f.engine.request({ method: "GET", path: SESSION });
  await f.engine.request(READ);
  await f.engine.request(
    { method: "POST", path: "/api/v1/desktop/auth/login", body: { password: "never persisted" } },
    async () => ({ ok: false, failure: "http", status: 401, data: {} }),
  );
  expect(f.engine.status().available).toBe(false);
  f.disconnect();
  expect((await f.engine.request(READ)).ok).toBe(false);
  expect((await fs.readFile(path.join(directory, "local.enc"))).toString()).not.toContain("never persisted");
});

it("never falls back on a permission denial and expires offline access after 24 hours", async () => {
  const f = fixture();
  await f.engine.request({ method: "GET", path: SESSION });
  await f.engine.request(READ);
  const denied = await f.engine.request(READ, async () => ({
    ok: false,
    failure: "http",
    status: 403,
    data: { error: "denied" },
  }));
  expect(denied.ok).toBe(false);
  expect(f.engine.status().available).toBe(false);
  await f.engine.request({ method: "GET", path: SESSION });
  const expired = new OfflineEngine(
    store,
    "https://finora.test",
    async () => unavailable,
    () => Date.now() + 25 * 60 * 60_000,
  );
  expect(await expired.request({ method: "GET", path: SESSION })).toEqual({
    ok: false,
    failure: "unauthenticated",
  });
  await expect(expired.saveSupplierDraft(draft)).rejects.toThrow("تسجيل دخول حديث");
});

it("isolates queued operations when the authenticated branch scope changes", async () => {
  const f = fixture();
  await f.engine.request({ method: "GET", path: SESSION });
  await f.engine.request(READ);
  await f.engine.saveSupplierDraft(draft);
  const switched = { ...session, branch_scope: "all" };
  await f.engine.request({ method: "GET", path: SESSION }, async () => ({
    ok: true,
    status: 200,
    data: { ok: true, session: switched },
  }));
  expect(f.engine.status().pending).toBe(0);
  expect(f.engine.status().operations).toEqual([]);
  f.disconnect();
  expect((await f.engine.request(READ)).ok).toBe(false);
  await f.engine.request({ method: "GET", path: SESSION }, async () => ({
    ok: true,
    status: 200,
    data: { ok: true, session },
  }));
  expect(f.engine.status().pending).toBe(1);
  await f.engine.synchronize();
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")).toHaveLength(0);
});

it("durably records a draft and prevents two local drafts claiming the same last piece", async () => {
  const f = fixture();
  await f.engine.request({ method: "GET", path: SESSION });
  await f.engine.request(READ);
  const outcomes = await Promise.allSettled([
    f.engine.saveSupplierDraft(draft),
    f.engine.saveSupplierDraft(draft),
  ]);
  expect(outcomes.filter((r) => r.status === "fulfilled")).toHaveLength(1);
  expect(f.engine.status().pending).toBe(1);
  await store.close();
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
  const restored = new OfflineEngine(store, "https://finora.test", async () => unavailable);
  expect(restored.status().operations).toHaveLength(1);
  expect(restored.status().operations[0]?.status).toBe("pending");
});

it("replays the same UUID after a server commit whose reply was lost", async () => {
  const f = fixture();
  await f.engine.request({ method: "GET", path: SESSION });
  await f.engine.request(READ);
  const saved = await f.engine.saveSupplierDraft(draft);
  let attempts = 0;
  const ids: unknown[] = [];
  const sender = async (r: FinoraRequest): Promise<FinoraResponse> => {
    if (r.method === "GET") return { ok: true, status: 200, data: { ok: true, session } };
    const body = r.body as { operation_id: string };
    ids.push(body.operation_id);
    attempts += 1;
    return attempts === 1
      ? unavailable
      : { ok: true, status: 200, data: { success: true, invoice_no: "SS-1" } };
  };
  const first = new OfflineEngine(store, "https://finora.test", sender);
  await first.synchronize();
  expect(first.status().pending).toBe(1);
  await store.close();
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
  const restored = new OfflineEngine(store, "https://finora.test", sender);
  await restored.synchronize();
  expect(restored.status().operations[0]).toMatchObject({ id: saved.id, status: "done", invoiceNo: "SS-1" });
  expect(ids).toEqual([saved.id, saved.id]);
});

it("keeps a stock conflict without automatic replay and permits explicit revalidation", async () => {
  const f = fixture();
  await f.engine.request({ method: "GET", path: SESSION });
  await f.engine.request(READ);
  const saved = await f.engine.saveSupplierDraft(draft);
  let attempts = 0;
  const engine = new OfflineEngine(store, "https://finora.test", async (r) => {
    if (r.method === "GET") return { ok: true, status: 200, data: { ok: true, session } };
    attempts += 1;
    return attempts === 1
      ? { ok: false, failure: "http", status: 409, data: { error: "لا يوجد مخزون" } }
      : { ok: true, status: 200, data: { success: true, invoice_no: "SS-2" } };
  });
  await engine.synchronize();
  await engine.synchronize();
  expect(attempts).toBe(1);
  expect(engine.status().operations[0]).toMatchObject({ status: "conflict", error: "لا يوجد مخزون" });
  await engine.retry(saved.id);
  expect(engine.status().operations[0]?.status).toBe("done");
});

it("rolls back the in-memory mutation on a failed checkpoint and refuses corrupt files", async () => {
  vi.spyOn(fs, "rename").mockRejectedValueOnce(new Error("disk full"));
  await expect(
    store.write(() => store.run("INSERT INTO metadata VALUES ('not-durable','private')")),
  ).rejects.toThrow("disk full");
  expect(store.one("SELECT value FROM metadata WHERE key='not-durable'")).toBeUndefined();
  await store.close();
  store = await OfflineDatabase.open(path.join(directory, "local.enc"), key, wasm);
  const bytes = await fs.readFile(path.join(directory, "local.enc"));
  bytes[bytes.length - 1] = (bytes[bytes.length - 1] ?? 0) ^ 1;
  await fs.writeFile(path.join(directory, "damaged.enc"), bytes);
  await expect(OfflineDatabase.open(path.join(directory, "damaged.enc"), key, wasm)).rejects.toThrow();
  expect(await fs.readFile(path.join(directory, "damaged.enc"))).toEqual(bytes);
});
