import { z } from "zod";
import { OfflineDatabase } from "./offlineDatabase";
const scalar = z.union([z.string(), z.number().finite(), z.null()]);
export const portableSchema = z
  .object({
    version: z.literal(1),
    server: z.string(),
    scope: z.string().regex(/^[a-f0-9]{64}$/),
    device: z.string().uuid(),
    counter: z.number().int().nonnegative(),
    permissions: z.array(z.string()),
    createdAt: z.string(),
    tables: z.record(z.array(z.record(scalar))),
  })
  .strict();
type Portable = z.infer<typeof portableSchema>;
function scopedTables(store: OfflineDatabase) {
  return store
    .all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    .map((r) => String(r.name))
    .filter(
      (name) =>
        /^[a-z_]+$/.test(name) && store.all(`PRAGMA table_info(${name})`).some((r) => r.name === "scope"),
    );
}
export async function exportScoped(
  store: OfflineDatabase,
  server: string,
  scope: string,
  permissions: string[],
): Promise<Portable> {
  await store.settled();
  const tables: Portable["tables"] = {};
  for (const name of scopedTables(store))
    tables[name] = store.all(`SELECT * FROM ${name} WHERE scope=?`, [scope]) as Portable["tables"][string];
  tables.operation_reservations = store.all(
    "SELECT * FROM operation_reservations WHERE operation_id IN (SELECT id FROM operations WHERE scope=?)",
    [scope],
  ) as Portable["tables"][string];
  return portableSchema.parse({
    version: 1,
    server,
    scope,
    permissions,
    createdAt: new Date().toISOString(),
    device: store.one("SELECT value FROM metadata WHERE key='device'")?.value,
    counter: Number(store.one("SELECT value FROM metadata WHERE key='receipt-counter'")?.value ?? 0),
    tables,
  });
}
export function pendingLocalWork(store: OfflineDatabase, scope: string) {
  return (
    !!store.one("SELECT id FROM operations WHERE scope=? AND status NOT IN ('done','cancelled') LIMIT 1", [
      scope,
    ]) ||
    ["customer_commands", "audit_commands", "stock_commands"].some(
      (name) =>
        scopedTables(store).includes(name) &&
        !!store.one(`SELECT 1 FROM ${name} WHERE scope=? LIMIT 1`, [scope]),
    ) ||
    !!store.one("SELECT 1 FROM stock_requests WHERE scope=? AND state='pending' LIMIT 1", [scope])
  );
}
export function restoreBlocked(store: OfflineDatabase, scope: string, device: string) {
  const sameDevice = store.one("SELECT value FROM metadata WHERE key='device'")?.value === device;
  return (
    store.all("SELECT id FROM contexts").some((row) => pendingLocalWork(store, String(row.id))) ||
    !!store.one("SELECT 1 FROM device_stock WHERE (scope<>? OR ?=0) AND quantity>used+returned LIMIT 1", [
      scope,
      sameDevice ? 1 : 0,
    ])
  );
}
export async function importScoped(
  store: OfflineDatabase,
  value: unknown,
  server: string,
  scope: string,
  permissions: string[],
) {
  const backup = portableSchema.parse(value);
  if (
    backup.server !== server ||
    backup.scope !== scope ||
    JSON.stringify([...backup.permissions].sort()) !== JSON.stringify([...permissions].sort())
  )
    throw Error("النسخة تخص خادماً أو حساباً أو فرعاً أو صلاحيات مختلفة");
  const allowed = new Set([...scopedTables(store), "operation_reservations"]);
  for (const [name, rows] of Object.entries(backup.tables)) {
    if (!allowed.has(name)) throw Error("بنية النسخة غير مدعومة");
    const columns = store.all(`PRAGMA table_info(${name})`).map((r) => String(r.name));
    const operationIds = new Set((backup.tables.operations ?? []).map((r) => r.id));
    for (const row of rows) {
      if (Object.keys(row).some((key) => !columns.includes(key)) || columns.some((key) => !(key in row)))
        throw Error("أعمدة النسخة غير متوافقة مع هذا الإصدار");
      if (name === "operation_reservations" ? !operationIds.has(row.operation_id) : row.scope !== scope)
        throw Error("سياق النسخة غير صالح");
    }
  }
  await store.write(() => {
    if (pendingLocalWork(store, scope)) throw Error("أكمل العمليات المحلية الحالية قبل الاستعادة");
    store.run(
      "DELETE FROM operation_reservations WHERE operation_id IN (SELECT id FROM operations WHERE scope=?)",
      [scope],
    );
    for (const [name, rows] of Object.entries(backup.tables)) {
      if (name === "operation_reservations")
        store.run(
          "DELETE FROM operation_reservations WHERE operation_id IN (SELECT id FROM operations WHERE scope=?)",
          [scope],
        );
      else store.run(`DELETE FROM ${name} WHERE scope=?`, [scope]);
      const columns = store.all(`PRAGMA table_info(${name})`).map((r) => String(r.name));
      for (const row of rows)
        store.run(
          `INSERT INTO ${name} (${columns.join(",")}) VALUES (${columns.map(() => "?").join(",")})`,
          columns.map((key) => row[key] ?? null),
        );
    }
    store.run("INSERT OR REPLACE INTO metadata VALUES ('device',?)", [backup.device]);
    store.run("INSERT OR REPLACE INTO metadata VALUES ('receipt-counter',?)", [
      String(Math.max(backup.counter, Math.floor(Date.now() / 1000))),
    ]);
    store.run("UPDATE device_stock SET frozen=1 WHERE scope=?", [scope]);
    if (permissions.some((p) => p === "view_pos" || p === "can_manage_suppliers"))
      store.run("INSERT OR REPLACE INTO metadata VALUES (?, '1')", [`restored-stock:${scope}`]);
  });
}
