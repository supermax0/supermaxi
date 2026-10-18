import { randomBytes, randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { OfflineDatabase } from "./offlineDatabase";
import { InventoryAudit } from "./inventoryAudit";
import { sessionSchema } from "../../src/api/finora/schemas";
import { auditRequired, auditBase, auditLineSchema, auditSessionSchema } from "../../shared/inventoryAudit";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";

const auth = "/api/v1/desktop/auth/session",
  now = Date.now();
const session = sessionSchema.parse({
  user: { id: 7, name: "Counter", username: "counter", role: "cashier" },
  tenant: { id: 3, slug: "audit-company", name: "Company", business_type: "general" },
  branch: { id: 1, name: "Branch" },
  branch_scope: "branch",
  roles: ["counter"],
  permissions: [
    "inventory.audit.view",
    "inventory.audit.count",
    "inventory.audit.system",
    "inventory.audit.cost",
    "inventory.audit.investigate",
    "inventory.audit.approve",
    "inventory.audit.post",
  ],
  session_max_age_seconds: 604800,
});
const line = auditLineSchema.parse({
  id: 11,
  location_key: "branch:1",
  branch_id: 1,
  warehouse_id: null,
  product: {
    id: 2,
    name: "TV",
    sku: "TV55",
    barcode: "88055",
    image_url: "",
    model: "55",
    variant_id: 0,
    variant_name: "",
    unit: "قطعة",
    unit_cost: 100,
  },
  version: 1,
  counted_quantity: null,
  expected_quantity: null,
  baseline_quantity: 12,
  current_quantity: null,
  difference: null,
  status: "uncounted",
  conflict: false,
  counted_at: null,
  counted_by: null,
  notes: "",
  excluded: false,
  resolution: "unreviewed",
  resolution_note: "",
  reviewed_by: null,
  reviewed_at: null,
  posted_delta: null,
  posted_cost: null,
  movement_id: null,
  journal_entry_id: null,
});
const row = auditSessionSchema.parse({
  id: 1,
  number: "INV-TEST",
  title: "",
  ledger_kind: "branch",
  locations: [{ key: "branch:1", name: "Branch", branch_name: "Branch", branch_id: 1, warehouse_id: null }],
  status: "counting",
  version: 1,
  created_by: 7,
  created_by_name: "Counter",
  created_at: new Date(now).toISOString(),
  submitted_at: null,
  approved_by: null,
  approved_at: null,
  posted_by: null,
  posted_at: null,
  review_note: "",
  stats: {
    planned: 1,
    counted: 0,
    uncounted: 1,
    excluded: 0,
    unreviewed: 0,
    matched: 0,
    shortage: 0,
    surplus: 0,
    shortage_units: 0,
    surplus_units: 0,
    net_units: 0,
  },
});
const ok = (data: unknown): FinoraResponse => ({ ok: true, status: 200, data: { success: true, data } });
const offline: FinoraResponse = { ok: false, failure: "network" };
let directory: string, file: string, key: Buffer, store: OfflineDatabase;
beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-inventory-audit-test-"));
  file = path.join(directory, "counts.enc");
  key = randomBytes(32);
  store = await OfflineDatabase.open(file, key, path.resolve("node_modules/sql.js/dist/sql-wasm.wasm"));
});
afterEach(async () => {
  vi.restoreAllMocks();
  await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-inventory-audit-test-")
  )
    throw Error("Unsafe cleanup");
  await fs.rm(directory, { recursive: true, force: true });
});
function fixture() {
  let context: { id: string; session: typeof session } | null = { id: "server-a/audit-company/7/1", session },
    manual = false,
    live = session;
  let reply: FinoraResponse = offline;
  const sender = vi.fn(async (request: FinoraRequest): Promise<FinoraResponse> =>
    request.path === auth ? { ok: true, status: 200, data: { ok: true, session: live } } : reply,
  );
  const engine = new InventoryAudit(
    store,
    () => context,
    async (s) => {
      if (context) context = { ...context, session: s };
    },
    async () => {
      context = null;
    },
    () => manual,
    () => now,
  );
  return {
    engine,
    sender,
    setOffline: (value: boolean) => {
      manual = value;
    },
    setReply: (value: FinoraResponse) => {
      reply = value;
    },
    setLive: (value: typeof session) => {
      live = value;
    },
    setContext: (value: typeof context) => {
      context = value;
    },
    makeRestart: () =>
      new InventoryAudit(
        store,
        () => context,
        async (s) => {
          if (context) context = { ...context, session: s };
        },
        async () => {
          context = null;
        },
        () => manual,
        () => now,
      ),
  };
}
function command(
  action: string,
  extra: Record<string, string | number | number[] | boolean> = {},
): FinoraRequest {
  return {
    method: "POST",
    path: `${auditBase}/1/commands`,
    body: { action, idempotency_key: randomUUID(), ...extra },
  };
}
async function acknowledge(f: ReturnType<typeof fixture>, request: FinoraRequest, response: FinoraResponse) {
  if (!response.ok) throw Error("not confirmed");
  const body = request.body as Record<string, unknown>;
  expect(
    (
      await f.engine.request(
        {
          method: "POST",
          path: `${auditBase}/local/actions`,
          body: {
            operation: "ack",
            key: String(body.idempotency_key),
            path: request.path,
            scope: auditRequired(response.auditCommandScope),
          },
        },
        f.sender,
      )
    ).ok,
  ).toBe(true);
}
async function prepare(f: ReturnType<typeof fixture>) {
  const ticket = randomUUID(),
    request = command("prepare_offline", { line_ids: [11] });
  f.setReply(
    ok({
      session_id: 1,
      snapshot: row,
      snapshot_permissions: ["inventory.audit.system", "inventory.audit.cost"],
      records: [{ line, ticket, version: 1, issued_at: new Date(now).toISOString(), expected_quantity: 12 }],
    }),
  );
  const response = await f.engine.request(request, f.sender);
  expect(response.ok).toBe(true);
  await acknowledge(f, request, response);
  return ticket;
}
async function count(f: ReturnType<typeof fixture>, quantity = 10) {
  f.setOffline(true);
  const begin = await f.engine.request(command("begin_count", { line_id: 11, version: 1 }), f.sender);
  expect(begin.ok).toBe(true);
  if (!begin.ok) throw Error("missing ticket");
  const data = (begin.data as { data: { ticket: string; version: number } }).data;
  const request = command("save_count", {
    line_id: 11,
    version: data.version,
    ticket: data.ticket,
    quantity,
    notes: "Private counted evidence",
  });
  const result = await f.engine.request(request, f.sender);
  expect(result.ok).toBe(true);
  return { request, result };
}
it("rejects a structurally valid snapshot for different requested lines before caching any private records", async () => {
  const f = fixture();
  f.setReply(
    ok({
      session_id: 1,
      snapshot: row,
      snapshot_permissions: ["inventory.audit.system", "inventory.audit.cost"],
      records: [
        {
          line,
          ticket: randomUUID(),
          version: 1,
          issued_at: new Date(now).toISOString(),
          expected_quantity: 12,
        },
      ],
    }),
  );
  const response = await f.engine.request(command("prepare_offline", { line_ids: [12] }), f.sender);
  expect(response).toEqual({ ok: false, failure: "invalid_response" });
  expect(f.engine.status().prepared_records).toBe(0);
  expect(f.engine.status().items[0]?.state).toBe("uncertain");
});
it("downloads only validated actor snapshots and persists encrypted counts across restart without financial posts", async () => {
  const f = fixture();
  await prepare(f);
  f.sender.mockClear();
  await count(f);
  expect(f.sender).not.toHaveBeenCalled();
  expect(f.engine.status().items[0]?.state).toBe("pending");
  const bytes = await fs.readFile(file);
  expect(bytes.includes(Buffer.from("Private counted evidence"))).toBe(false);
  await store.close();
  store = await OfflineDatabase.open(file, key, path.resolve("node_modules/sql.js/dist/sql-wasm.wasm"));
  const restarted = f.makeRestart();
  const data = await restarted.request(
    { method: "GET", path: `${auditBase}/1/lines`, query: { counted: true } },
    f.sender,
  );
  expect(data.ok && data.source).toBe("offline");
  expect(data.ok ? data.data : null).toMatchObject({
    success: true,
    data: { items: [{ counted_quantity: 10, expected_quantity: 12, difference: -2 }] },
  });
  for (const action of ["approve", "post", "submit", "pause", "resume"])
    expect((await restarted.request(command(action, { version: 1 }), f.sender)).ok).toBe(false);
  expect(f.sender).not.toHaveBeenCalled();
});
it("manual synchronization preserves exact UUID and observation time, waits for full confirmation, then acknowledges", async () => {
  const f = fixture();
  await prepare(f);
  await count(f);
  // Manual retry must probe the server even while the last connection state is offline.
  const saved = auditRequired(f.engine.status().items[0]);
  f.setReply(ok({ session_id: 1, line_id: 11, version: 2 }));
  const response = await f.engine.request(
    { method: "POST", path: `${auditBase}/local/actions`, body: { operation: "retry", key: saved.key } },
    f.sender,
  );
  expect(response.ok).toBe(true);
  expect(f.engine.status().items[0]?.state).toBe("confirmed");
  const posted = f.sender.mock.calls.filter(([request]) => request.method === "POST").at(-1)?.[0];
  expect(posted?.body).toMatchObject({
    idempotency_key: saved.key,
    action: "save_offline_count",
    quantity: 10,
    counted_at: new Date(now).toISOString(),
  });
  await acknowledge(f, { ...auditRequired(posted), body: { idempotency_key: saved.key } }, response);
  expect(f.engine.status().items).toEqual([]);
});
it("stock conflicts keep original counts and reasoned discard removes the stale snapshot without posting", async () => {
  const f = fixture();
  await prepare(f);
  await count(f);
  f.setOffline(false);
  const saved = auditRequired(f.engine.status().items[0]);
  f.setReply({ ok: false, failure: "http", status: 409, data: { error: "حدثت حركة بعد اللقطة" } });
  await f.engine.request(
    { method: "POST", path: `${auditBase}/local/actions`, body: { operation: "retry", key: saved.key } },
    f.sender,
  );
  expect(f.engine.status().items[0]?.state).toBe("conflict");
  const discard = await f.engine.request(
    {
      method: "POST",
      path: `${auditBase}/local/actions`,
      body: { operation: "discard", key: saved.key, reason: "أعيد العد بعد الحركة" },
    },
    f.sender,
  );
  expect(discard.ok).toBe(true);
  expect(f.engine.status().prepared_records).toBe(0);
  expect(store.all("SELECT action FROM audit_local_history").map((item) => item.action)).toEqual([
    "save_offline_count",
    "discard_offline_count",
  ]);
});
it("recounts an unsent local observation by replacement and never adds parallel count quantities", async () => {
  const f = fixture();
  await prepare(f);
  await count(f, 10);
  await count(f, 9);
  expect(f.engine.status().items).toHaveLength(1);
  const queued = JSON.parse(String(store.one("SELECT payload FROM audit_commands")?.payload));
  expect(queued.body.quantity).toBe(9);
  expect(store.all("SELECT action FROM audit_local_history")).toHaveLength(2);
});
it("unknown outcomes cannot be replaced or discarded and replay the original command after process restart", async () => {
  const f = fixture();
  const original = {
    method: "POST" as const,
    path: auditBase,
    body: {
      idempotency_key: randomUUID(),
      ledger_kind: "branch",
      location_keys: ["branch:1"],
      title: "New count",
    },
  };
  expect(await f.engine.request(original, f.sender)).toEqual(offline);
  const saved = auditRequired(f.engine.status().items[0]);
  expect(saved.state).toBe("uncertain");
  expect(
    (
      await f.engine.request(
        { ...original, body: { ...original.body, idempotency_key: randomUUID() } },
        f.sender,
      )
    ).ok,
  ).toBe(false);
  expect(
    (
      await f.engine.request(
        {
          method: "POST",
          path: `${auditBase}/local/actions`,
          body: { operation: "discard", key: saved.key, reason: "uncertain" },
        },
        f.sender,
      )
    ).ok,
  ).toBe(false);
  await store.close();
  store = await OfflineDatabase.open(file, key, path.resolve("node_modules/sql.js/dist/sql-wasm.wasm"));
  const restarted = f.makeRestart();
  f.setReply(ok({ session_id: 4 }));
  f.sender.mockClear();
  const reply = await restarted.request(
    { method: "POST", path: `${auditBase}/local/actions`, body: { operation: "retry", key: saved.key } },
    f.sender,
  );
  expect(reply.ok).toBe(true);
  expect(f.sender.mock.calls.filter(([r]) => r.method === "POST")[0]?.[0].body).toMatchObject(original.body);
});
it("fresh authorization prevents replay after count permission revocation and isolates server/tenant/user/branch caches", async () => {
  const f = fixture();
  await prepare(f);
  await count(f);
  f.setOffline(false);
  const saved = auditRequired(f.engine.status().items[0]);
  f.setLive({ ...session, permissions: ["inventory.audit.view"] });
  f.sender.mockClear();
  expect(
    (
      await f.engine.request(
        { method: "POST", path: `${auditBase}/local/actions`, body: { operation: "retry", key: saved.key } },
        f.sender,
      )
    ).ok,
  ).toBe(false);
  expect(f.sender.mock.calls.some(([request]) => request.method === "POST")).toBe(false);
  f.setContext({ id: "server-b/audit-company/7/1", session });
  expect(f.engine.status().items).toHaveLength(0);
  f.setContext({
    id: "server-a/audit-company/7/1",
    session: { ...session, tenant: { ...session.tenant, id: 9 } },
  });
  expect(f.engine.status().items).toHaveLength(0);
  f.setContext({
    id: "server-a/audit-company/7/1",
    session: { ...session, user: { ...session.user, id: 8 } },
  });
  expect(f.engine.status().items).toHaveLength(0);
  f.setContext({
    id: "server-a/audit-company/7/1",
    session: { ...session, branch: { id: 2, name: "Other" } },
  });
  expect(f.engine.status().items).toHaveLength(0);
});
it("malformed download receipts remain uncertain and cannot seed offline quantities", async () => {
  const f = fixture();
  f.setReply(ok({ session_id: 1, snapshot: row, records: [{ line, ticket: "invalid" }] }));
  await f.engine.request(command("prepare_offline", { line_ids: [11] }), f.sender);
  expect(f.engine.status().prepared_records).toBe(0);
  expect(f.engine.status().items[0]?.state).toBe("uncertain");
});
it("failed encrypted checkpoint prevents transmission and changed context during checkpoint prevents sending old IDs", async () => {
  const f = fixture(),
    original = command("investigate", { line_id: 11 });
  vi.spyOn(store, "write").mockRejectedValueOnce(Error("disk full"));
  await expect(f.engine.request(original, f.sender)).rejects.toThrow("disk full");
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  vi.restoreAllMocks();
  const write = store.write.bind(store);
  vi.spyOn(store, "write").mockImplementationOnce(async (action) => {
    const result = await write(action);
    f.setContext({ id: "server-b/audit-company/7/1", session });
    return result;
  });
  expect((await f.engine.request(original, f.sender)).ok).toBe(false);
  expect(f.sender.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
});
