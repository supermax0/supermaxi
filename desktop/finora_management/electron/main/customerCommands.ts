import { createHash } from "node:crypto";
import { z } from "zod";
import { finoraRequestSchema, type FinoraRequest, type FinoraResponse } from "../../shared/ipc";
import {
  customerCommandKey,
  customerCommandPath,
  isCustomerCommand,
  type SavedCustomerCommand,
} from "../../shared/customerRecovery";
import { sessionEnvelopeSchema, type FinoraSession } from "../../src/api/finora/schemas";
import { isStockCommand, stockCommandPath, stockCommandAllowed } from "../../shared/stockRecovery";
import type { OfflineDatabase } from "./offlineDatabase";

type Context = { id: string; session: FinoraSession };
type Sender = (request: FinoraRequest) => Promise<FinoraResponse>;
const confirmed = z.object({ success: z.literal(true), data: z.object({ id: z.number().int().positive() }) });
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
function identity(session: FinoraSession): string {
  return JSON.stringify([
    session.tenant.id,
    session.tenant.slug,
    session.user.id,
    session.branch?.id ?? null,
    session.branch_scope ?? "branch",
  ]);
}
function scope(context: Context): string {
  return createHash("sha256")
    .update(JSON.stringify([context.id, identity(context.session)]))
    .digest("hex");
}
function allowed(context: Context, path: string, area: "customers" | "stock" = "customers"): boolean {
  if (area === "stock") return stockCommandAllowed(context.session, path);
  const permissions = context.session.permissions;
  return (
    permissions.includes("manage_customers") &&
    (!path.endsWith("/debts") ||
      (permissions.includes("finance.view") && permissions.includes("finance.settings")))
  );
}
function command(request: FinoraRequest, area: "customers" | "stock" = "customers") {
  const parsed = finoraRequestSchema.parse(request);
  if (
    !(area === "stock" ? isStockCommand(parsed) : isCustomerCommand(parsed)) ||
    !(area === "stock" ? stockCommandPath(parsed.path) : customerCommandPath(parsed.path)) ||
    parsed.query ||
    !parsed.body ||
    typeof parsed.body !== "object" ||
    Array.isArray(parsed.body)
  )
    throw Error("طلب العميل غير صالح");
  const key = customerCommandKey.parse(
    area === "stock" ? parsed.body.operation_id : parsed.body.idempotency_key,
  );
  const payload = canonical({ method: parsed.method, path: parsed.path, body: parsed.body });
  if (Buffer.byteLength(payload) > 256_000) throw Error("طلب العميل أكبر من الحد المسموح");
  let target = parsed.path;
  if (target.endsWith("/commands")) {
    if (parsed.body.operation === "create") target += ":create";
    else if (
      parsed.body.operation === "update" &&
      typeof parsed.body.id === "number" &&
      Number.isSafeInteger(parsed.body.id) &&
      parsed.body.id > 0
    )
      target += `:update:${parsed.body.id}`;
    else throw Error("عملية ملف العميل غير صالحة");
  }
  // Manual edits and repartitioning compete for the same schedule.
  target = target.replace(/\/(schedule|repartition)$/, "");
  if (area === "stock")
    target = /\/(send|receive|cancel|reverse)$/.test(parsed.path)
      ? parsed.path.replace(/\/(send|receive|cancel|reverse)$/, "")
      : `${parsed.path}:${parsed.body.location_key ?? parsed.body.from_location ?? parsed.body.code ?? ""}:${parsed.body.product_id ?? ""}:${parsed.body.variant_name ?? parsed.body.to_location ?? ""}`;
  return { request: parsed, key, target, fingerprint: createHash("sha256").update(payload).digest("hex") };
}
const refused = (message: string): FinoraResponse => ({
  ok: false,
  failure: "http",
  status: 409,
  data: { success: false, error: message },
});

/** Write-ahead requests, never an offline financial ledger or an automatic replay queue. */
export class CustomerCommands {
  private tail: Promise<unknown> = Promise.resolve();
  constructor(
    private store: OfflineDatabase,
    private context: () => Context | null,
    private now = Date.now,
    private remember?: (session: FinoraSession) => Promise<void>,
    private deactivate?: () => Promise<void>,
    private area: "customers" | "stock" = "customers",
  ) {}

  private effectiveContext(): Context | null {
    const current = this.context();
    return current && this.area === "stock" ? { ...current, id: `${current.id}:stock-operations` } : current;
  }

  list() {
    const context = this.effectiveContext();
    if (!context || !allowed(context, "", this.area)) return { available: false, items: [] };
    const items = this.store
      .all("SELECT * FROM customer_commands WHERE scope=? ORDER BY created,key", [scope(context)])
      .filter((row) => allowed(context, String(row.path), this.area))
      .map((row): SavedCustomerCommand => ({
        key: String(row.key),
        request: finoraRequestSchema.parse(JSON.parse(String(row.payload))),
        created: Number(row.created),
        state: row.state === "confirmed" ? "confirmed" : "uncertain",
      }));
    return { available: true, items };
  }

  execute(input: FinoraRequest, sender: Sender): Promise<FinoraResponse> {
    const task = this.tail.then(() => this.send(input, sender));
    this.tail = task.catch(() => undefined);
    return task;
  }

  private async send(input: FinoraRequest, sender: Sender): Promise<FinoraResponse> {
    let data;
    try {
      data = command(input, this.area);
    } catch {
      return {
        ok: false,
        failure: "http",
        status: 400,
        data: { error: "طلب العميل أو رقم العملية غير صالح" },
      };
    }
    const context = this.effectiveContext();
    if (!context || !allowed(context, data.request.path, this.area))
      return { ok: false, failure: "unauthenticated" };
    // A lease or a cached GET is insufficient to authorize replay.
    const verified = await sender({ method: "GET", path: "/api/v1/desktop/auth/session" });
    if (!verified.ok) {
      if (
        ["unauthenticated", "password_change_required"].includes(verified.failure) ||
        verified.status === 401 ||
        verified.status === 403
      )
        await this.deactivate?.();
      return verified;
    }
    if (verified.source) return { ok: false, failure: "network" };
    const live = sessionEnvelopeSchema.safeParse(verified.data);
    if (!live.success) return { ok: false, failure: "invalid_response" };
    if (identity(live.data) !== identity(context.session) || this.effectiveContext()?.id !== context.id) {
      await this.deactivate?.();
      return { ok: false, failure: "unauthenticated" };
    }
    await this.remember?.(live.data);
    if (!allowed({ ...context, session: live.data }, data.request.path, this.area))
      return {
        ok: false,
        failure: "http",
        status: 403,
        data: { error: "لم تعد لديك صلاحية تنفيذ طلب العميل" },
      };
    let existed = false;
    const conflict = await this.store.write(() => {
      const old = this.store.one("SELECT fingerprint FROM customer_commands WHERE scope=? AND key=?", [
        scope(context),
        data.key,
      ]);
      existed = !!old;
      if (old)
        return old.fingerprint !== data.fingerprint
          ? "لا يمكن تغيير بيانات طلب محفوظ؛ استرجع الطلب الأصلي"
          : "";
      if (
        this.store.one("SELECT key FROM customer_commands WHERE scope=? AND target=?", [
          scope(context),
          data.target,
        ])
      )
        return "يوجد طلب حفظ لهذا المصدر؛ راجع طلبات الحفظ المحفوظة قبل إنشاء طلب آخر";
      const count = Number(
        this.store.one("SELECT COUNT(*) AS n FROM customer_commands WHERE scope=?", [scope(context)])?.n ?? 0,
      );
      if (count >= 100) return "راجع طلبات الحفظ المحفوظة قبل إضافة المزيد";
      this.store.run(
        "INSERT INTO customer_commands(scope,key,path,target,payload,fingerprint,created,state) VALUES(?,?,?,?,?,?,?,'uncertain')",
        [
          scope(context),
          data.key,
          data.request.path,
          data.target,
          JSON.stringify(data.request),
          data.fingerprint,
          this.now(),
        ],
      );
      return "";
    });
    if (conflict) return refused(conflict);
    const current = this.effectiveContext();
    if (!current || scope(current) !== scope(context)) return { ok: false, failure: "unauthenticated" };
    const response = await sender(data.request);
    if (
      !response.ok &&
      (["unauthenticated", "password_change_required"].includes(response.failure) ||
        response.status === 401 ||
        (response.status === 403 && this.area === "customers"))
    )
      await this.deactivate?.();
    if (response.ok && confirmed.safeParse(response.data).success) {
      await this.store.write(() =>
        this.store.run("UPDATE customer_commands SET state='confirmed' WHERE scope=? AND key=?", [
          scope(context),
          data.key,
        ]),
      );
    } else if (
      !existed &&
      !response.ok &&
      response.failure === "http" &&
      [400, 404, 409, 422].includes(response.status)
    ) {
      // Only a first-attempt, explicit business rejection proves this request did not commit.
      await this.store.write(() =>
        this.store.run("DELETE FROM customer_commands WHERE scope=? AND key=?", [scope(context), data.key]),
      );
    }
    return response.ok && confirmed.safeParse(response.data).success
      ? { ...response, customerCommandScope: scope(context) }
      : response;
  }

  async retry(key: string, sender: Sender) {
    customerCommandKey.parse(key);
    const saved = this.list().items.find((row) => row.key === key);
    if (!saved) throw Error("طلب الحفظ غير موجود ضمن صلاحياتك الحالية");
    return { request: saved.request, response: await this.execute(saved.request, sender) };
  }

  async acknowledge(key: string, path: string, expectedScope: string): Promise<void> {
    customerCommandKey.parse(key);
    const context = this.effectiveContext();
    if (!context || scope(context) !== expectedScope || !allowed(context, path, this.area))
      throw Error("الجلسة أو الصلاحية غير متاحة");
    await this.store.write(() =>
      this.store.run(
        "DELETE FROM customer_commands WHERE scope=? AND key=? AND path=? AND state='confirmed'",
        [scope(context), key, path],
      ),
    );
  }
}
