import { randomBytes } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { FinoraResponse } from "../../shared/ipc";
import { OfflineDatabase } from "./offlineDatabase";
import { HRCache } from "./hrCache";
import type { FinoraSession } from "../../src/api/finora/schemas";
let directory: string, store: OfflineDatabase;
const session: FinoraSession = {
  user: { id: 1, name: "HR", username: "hr", role: "admin" },
  tenant: { id: 1, slug: "hr-test", name: "HR", business_type: "general" },
  branch: { id: 1, name: "Main" },
  roles: ["admin"],
  permissions: ["hr.view"],
  session_max_age_seconds: 3600,
};
beforeEach(async () => {
  directory = await fs.mkdtemp(path.join(os.tmpdir(), "finora-hr-cache-"));
  store = await OfflineDatabase.open(
    path.join(directory, "private.enc"),
    randomBytes(32),
    path.resolve("node_modules/sql.js/dist/sql-wasm.wasm"),
  );
});
afterEach(async () => {
  await store.close();
  if (
    path.dirname(directory) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-hr-cache-")
  )
    throw new Error("Unsafe cleanup");
  await fs.rm(directory, { recursive: true, force: true });
});
it("publishes complete permission-filtered HR data atomically and keeps the previous snapshot on interruption", async () => {
  const people = [
    { id: 7, name: "علي", code: "EMP-7", phone: "0771", status: "active", branch_id: 1, department_id: 2 },
    { id: 8, name: "نور", code: "EMP-8", phone: "0772", status: "active", branch_id: 1, department_id: 3 },
  ];
  let fails = false,
    scope: { id: string; session: typeof session } | null = { id: "one", session };
  const cache = new HRCache(
    store,
    () => scope,
    async (request): Promise<FinoraResponse> => {
      if (fails) return { ok: false, failure: "network" };
      if (request.path.endsWith("/revision"))
        return { ok: true, status: 200, data: { revision: "one", scope_revision: "one" } };
      return {
        ok: true,
        status: 200,
        data: {
          revision: "one",
          scope_revision: "one",
          directory: { rows: people, page: 1, page_size: 100, total: 2, total_pages: 1 },
          details: people.map((person) => ({ person, history: [], contracts: [] })),
          lookups: { departments: [] },
          overview: { employees: 2 },
        },
      };
    },
  );
  await cache.download();
  expect(cache.status()).toMatchObject({ ready: true, people: 2 });
  expect(
    cache.query({ method: "GET", path: "/hr/api/page", query: { search: "نور", department_id: "3" } })?.data,
  ).toMatchObject({ total: 1, rows: [{ id: 8 }] });
  expect(cache.query({ method: "GET", path: "/hr/api/people/7" })?.data).toMatchObject({ person: { id: 7 } });
  expect(cache.query({ method: "GET", path: "/hr/api/documents/7" })).toBeNull();
  fails = true;
  await expect(cache.download()).rejects.toThrow();
  expect(cache.status().people).toBe(2);
  scope = { id: "other", session };
  expect(cache.status().ready).toBe(false);
  expect(cache.query({ method: "GET", path: "/hr/api/page" })).toBeNull();
  scope = null;
  expect(cache.status().ready).toBe(false);
});

it("keeps the last coherent snapshot when a paged download observes a central change", async () => {
  let revision = "v1",
    mutate = false;
  const cache = new HRCache(
    store,
    () => ({ id: "one", session }),
    async (request): Promise<FinoraResponse> => {
      if (request.path.endsWith("/revision"))
        return { ok: true, status: 200, data: { revision, scope_revision: "scope" } };
      const data = {
        revision,
        scope_revision: "scope",
        directory: { rows: [{ id: 7, name: revision }], page: 1, page_size: 100, total: 1, total_pages: 1 },
        details: [{ person: { id: 7 } }],
      };
      if (mutate) revision = "v2";
      return { ok: true, status: 200, data };
    },
    () => 1000,
  );
  await cache.download();
  mutate = true;
  await expect(cache.download()).rejects.toThrow("تغيّرت بيانات");
  expect(cache.query({ method: "GET", path: "/hr/api/page" })?.data).toMatchObject({
    rows: [{ name: "v1" }],
  });
});

it("shows offline leave and resource requests without treating them as centrally approved", async () => {
  await store.write(() => {
    store.run("INSERT INTO hr_snapshots VALUES (?,?,?,0)", [
      "one",
      JSON.stringify({
        people: [{ id: 7, name: "علي", code: "EMP-7" }],
        details: { "7": { person: { id: 7 } } },
        lookups: { leave_types: [{ id: 1, name: "سنوية" }] },
        overview: {},
        workspaces: { leave: [], resources: [] },
        startedAt: 900,
      }),
      1000,
    ]);
    for (const [action, payload] of [
      [
        "leave.request",
        { person_id: 7, type_id: 1, starts: "2026-10-12", ends: "2026-10-12", half_day: true, reason: "خاص" },
      ],
      ["resource.record", { person_id: 7, kind: "note", title: "ملاحظة محفوظة", note: "تفاصيل" }],
    ] as const) {
      store.run("INSERT INTO operations VALUES (?,?,?,?,?,?, 'pending',NULL,NULL)", [
        crypto.randomUUID(),
        "one",
        JSON.stringify({
          kind: "hr",
          command: { id: crypto.randomUUID(), action, payload },
          localAllowed: true,
          transmitted: false,
        }),
        "طلب",
        0,
        1100,
      ]);
    }
  });
  const cache = new HRCache(
    store,
    () => ({ id: "one", session }),
    async () => ({ ok: false, failure: "network" }),
    () => Date.parse("2026-10-10T12:00:00Z"),
  );
  expect(
    cache.query({ method: "GET", path: "/hr/api/workspace", query: { tab: "leave" } })?.data,
  ).toMatchObject({ rows: [{ status: "queued", days: 0.5, pending: true, type: "سنوية" }] });
  expect(
    cache.query({ method: "GET", path: "/hr/api/workspace", query: { tab: "resources" } })?.data,
  ).toMatchObject({ rows: [{ kind: "note", pending: true, detail: { title: "ملاحظة محفوظة" } }] });
});

it("overlays pending attendance and its exact acknowledgement until a newer complete snapshot exists", async () => {
  const attendance = {
    id: null,
    date: "2026-10-10",
    state: "scheduled",
    check_in: "",
    check_out: "",
    check_in_at: null,
    check_out_at: null,
    worked_minutes: 0,
    version: 0,
    shift: null,
  };
  await store.write(() => {
    store.run("INSERT INTO hr_snapshots VALUES (?,?,?,0)", [
      "one",
      JSON.stringify({
        people: [{ id: 7, name: "علي", attendance }],
        details: { "7": { person: { id: 7, name: "علي" }, attendance } },
        lookups: {},
        overview: {},
        workspaces: { "attendance:2026-10-10": [{ person_id: 7, ...attendance }] },
        startedAt: 900,
      }),
      1000,
    ]);
    for (const [index, event] of ["check_in", "check_out"].entries()) {
      const command = {
        id: crypto.randomUUID(),
        action: "attendance.record",
        payload: {
          person_id: 7,
          event,
          occurred_at: index === 0 ? "2026-10-10T05:00:00Z" : "2026-10-10T09:00:00Z",
        },
      };
      store.run("INSERT INTO operations VALUES (?,?,?,?,?,?, 'pending',NULL,NULL)", [
        command.id,
        "one",
        JSON.stringify({ kind: "hr", command, localAllowed: true, transmitted: false }),
        "دوام",
        0,
        1100,
      ]);
    }
  });
  const cache = new HRCache(
    store,
    () => ({ id: "one", session }),
    async () => ({ ok: false, failure: "network" }),
  );
  expect(cache.query({ method: "GET", path: "/hr/api/people/7" })?.data).toMatchObject({
    attendance: { check_in: "08:00", check_out: "12:00", worked_minutes: 240, pending: true },
  });
  await store.write(() => {
    const rows = store.all("SELECT id,payload FROM operations ORDER BY rowid");
    for (const row of rows) {
      const payload = JSON.parse(String(row.payload));
      payload.acknowledgedAt = 1200;
      store.run("UPDATE operations SET status='done',payload=?,invoice=? WHERE id=?", [
        JSON.stringify(payload),
        JSON.stringify({ success: true, id: 45, version: 2 }),
        String(row.id),
      ]);
    }
  });
  expect(cache.query({ method: "GET", path: "/hr/api/people/7" })?.data).toMatchObject({
    attendance: { id: 45, version: 2, pending: false, worked_minutes: 240 },
  });
});
