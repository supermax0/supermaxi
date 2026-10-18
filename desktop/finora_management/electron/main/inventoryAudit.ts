import { createHash } from "node:crypto";
import { z } from "zod";
import { finoraRequestSchema, type FinoraRequest, type FinoraResponse } from "../../shared/ipc";
import {
  auditBase,
  auditContext,
  auditReceiptSchema,
  auditLocalAction,
  auditLineSchema,
  auditSessionSchema,
  commandSchema,
  preparedAuditSchema,
  type AuditLine,
  type AuditSession,
} from "../../shared/inventoryAudit";
import { sessionEnvelopeSchema, type FinoraSession } from "../../src/api/finora/schemas";
import type { OfflineDatabase } from "./offlineDatabase";

type Context = { id: string; session: FinoraSession };
type Sender = (request: FinoraRequest) => Promise<FinoraResponse>;
const receipt = z.object({ success: z.literal(true), data: commandSchema });
const snapshot = z.object({ success: z.literal(true), data: preparedAuditSchema });
const reject = (message: string, status = 409): FinoraResponse => ({
  ok: false,
  failure: "http",
  status,
  data: { success: false, error: message },
});
const success = (data: unknown, offline = false): FinoraResponse => ({
  ok: true,
  status: 200,
  data: { success: true, data },
  ...(offline ? { source: "offline" as const } : {}),
});
const unavailable = (): FinoraResponse =>
  reject("نزّل أصناف الجرد باتصال حي أولاً؛ هذا الصنف غير متاح للعد بدون إنترنت", 409);
const permissionFor: Record<string, string> = {
  begin_count: "count",
  cancel_count: "count",
  release_ticket: "review",
  save_count: "count",
  save_offline_count: "count",
  prepare_offline: "count",
  submit: "count",
  pause: "count",
  resume: "count",
  review_line: "review",
  exclude: "review",
  reopen: "review",
  approve: "approve",
  post: "post",
  investigate: "investigate",
  transfer_draft: "review",
  create: "count",
};
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
const digest = (value: string) => createHash("sha256").update(value).digest("hex");
const scope = (context: Context) =>
  digest(
    JSON.stringify([
      context.id,
      context.session.tenant.id,
      context.session.tenant.slug,
      context.session.user.id,
      context.session.branch?.id ?? null,
      context.session.branch_scope ?? "branch",
    ]),
  );
const permissions = (context: Context) =>
  JSON.stringify(context.session.permissions.filter((key) => key.startsWith("inventory.audit.")).sort());
const allowed = (context: Context, action = "view") =>
  context.session.permissions.includes("inventory.audit.view") &&
  context.session.permissions.some((key) => key === `inventory.audit.${permissionFor[action] ?? action}`);
const network = (result: FinoraResponse) => !result.ok && ["network", "timeout"].includes(result.failure);

/** Counts and original retry payloads use FINORA's existing encrypted atomic SQLite checkpoint.
 * Only downloaded, actor-owned on-hand tickets can queue a local count. Financial transitions are online only. */
export class InventoryAudit {
  private tail: Promise<unknown> = Promise.resolve();
  private disconnected = false;
  private tickets = new Map<
    string,
    { line: AuditLine; ticket: string; version: number; expected?: number }
  >();
  constructor(
    private store: OfflineDatabase,
    private context: () => Context | null,
    private remember: (session: FinoraSession) => Promise<void>,
    private deactivate: () => Promise<void>,
    private forceOffline: () => boolean,
    private now = Date.now,
  ) {}

  private localContext() {
    const context = this.context();
    return context && allowed(context) ? context : null;
  }
  status() {
    const context = this.localContext();
    if (!context)
      return {
        available: false,
        offline: this.forceOffline() || this.disconnected,
        prepared_records: 0,
        items: [],
      };
    const own = scope(context);
    return {
      available: true,
      offline: this.forceOffline() || this.disconnected,
      prepared_records: Number(
        this.store.one("SELECT COUNT(*) AS n FROM audit_records WHERE scope=? AND permissions=?", [
          own,
          permissions(context),
        ])?.n ?? 0,
      ),
      items: this.store
        .all("SELECT * FROM audit_commands WHERE scope=? ORDER BY created,key", [own])
        .filter((row) => allowed(context, String(row.action)))
        .map((row) => ({
          key: String(row.key),
          session_id: row.session_id,
          line_id: row.line_id ?? null,
          action: String(row.action),
          created: Number(row.created),
          state: String(row.state),
          error: row.error === null ? null : String(row.error),
        })),
    };
  }
  async request(input: FinoraRequest, sender: Sender): Promise<FinoraResponse> {
    if (input.method === "GET" && input.path === `${auditBase}/local/status`) return success(this.status());
    if (input.path === `${auditBase}/local/actions`) {
      if (input.method !== "POST") return reject("إجراء غير صالح", 400);
      return this.serial(() => this.localAction(input, sender));
    }
    if (input.method === "POST") return this.serial(() => this.send(input, sender));
    const context = this.localContext();
    if (!context) return { ok: false, failure: "unauthenticated" };
    const id = input.path.match(
      /^\/api\/v1\/desktop\/inventory-audits\/(\d+)(?:$|\/lines(?:$|\/\d+\/details$))/,
    )?.[1];
    if (
      id &&
      this.store.one(
        "SELECT key FROM audit_commands WHERE scope=? AND session_id=? AND action='save_offline_count'",
        [scope(context), Number(id)],
      )
    )
      return this.read(input, context);
    if (this.forceOffline()) return this.read(input, context);
    const response = await sender(input);
    const afterRead = this.localContext();
    if (!afterRead || scope(afterRead) !== scope(context)) return { ok: false, failure: "unauthenticated" };
    if (network(response)) {
      this.disconnected = true;
      return this.read(input, context);
    }
    this.disconnected = false;
    if (
      !response.ok &&
      (response.status === 401 || response.status === 403 || response.failure === "unauthenticated")
    )
      await this.deactivate();
    return response;
  }
  private serial<T>(action: () => Promise<T>): Promise<T> {
    const result = this.tail.then(action);
    this.tail = result.catch(() => undefined);
    return result;
  }
  private async verify(context: Context, sender: Sender, reconnect = false): Promise<FinoraResponse | null> {
    if (this.forceOffline() && !reconnect) return { ok: false, failure: "network" };
    const response = await sender({ method: "GET", path: "/api/v1/desktop/auth/session" });
    if (!response.ok) {
      if (response.status === 401 || response.status === 403 || response.failure === "unauthenticated")
        await this.deactivate();
      return response;
    }
    if (response.source) return { ok: false, failure: "network" };
    const live = sessionEnvelopeSchema.safeParse(response.data);
    if (!live.success) return { ok: false, failure: "invalid_response" };
    if (scope({ ...context, session: live.data }) !== scope(context) || this.context()?.id !== context.id) {
      await this.deactivate();
      return { ok: false, failure: "unauthenticated" };
    }
    await this.remember(live.data);
    this.disconnected = false;
    return null;
  }
  private records(context: Context, id: number) {
    return this.store.all("SELECT * FROM audit_records WHERE scope=? AND session_id=? AND permissions=?", [
      scope(context),
      id,
      permissions(context),
    ]);
  }
  private session(context: Context, id: number): AuditSession | null {
    const record = this.store.one(
      "SELECT body FROM audit_sessions WHERE scope=? AND id=? AND permissions=?",
      [scope(context), id, permissions(context)],
    );
    if (!record) return null;
    const parsed = auditSessionSchema.safeParse(JSON.parse(String(record.body)));
    if (!parsed.success) return null;
    const row = parsed.data,
      lines = this.records(context, id).map((record) =>
        auditLineSchema.parse(JSON.parse(String(record.body))),
      );
    // Partial downloads retain the server's planned total. Missing records are never counted as zero.
    const observed = lines.filter((line) => line.counted_quantity !== null && !line.excluded);
    row.stats.counted = observed.length;
    row.stats.excluded = lines.filter((line) => line.excluded).length;
    row.stats.uncounted = Math.max(0, row.stats.planned - row.stats.counted - row.stats.excluded);
    if (context.session.permissions.includes("inventory.audit.system")) {
      const deltas = observed.map((line) => line.difference ?? 0);
      Object.assign(row.stats, {
        matched: deltas.filter((delta) => !delta).length,
        shortage: deltas.filter((delta) => delta < 0).length,
        surplus: deltas.filter((delta) => delta > 0).length,
        shortage_units: deltas.filter((delta) => delta < 0).reduce((sum, delta) => sum - delta, 0),
        surplus_units: deltas.filter((delta) => delta > 0).reduce((sum, delta) => sum + delta, 0),
        net_units: deltas.reduce((sum, delta) => sum + delta, 0),
        unreviewed: observed.filter((line) => line.difference && line.resolution === "unreviewed").length,
      });
    }
    return row;
  }
  private read(request: FinoraRequest, context: Context): FinoraResponse {
    const match = request.path.match(/^\/api\/v1\/desktop\/inventory-audits\/(\d+)(.*)$/);
    if (request.path === `${auditBase}/meta`) {
      const sessions = this.store
        .all("SELECT body FROM audit_sessions WHERE scope=? AND permissions=?", [
          scope(context),
          permissions(context),
        ])
        .map((row) => auditSessionSchema.parse(JSON.parse(String(row.body))));
      const locations = {
        branch: [] as AuditSession["locations"],
        warehouse: [] as AuditSession["locations"],
      };
      for (const row of sessions)
        for (const site of row.locations)
          if (!locations[row.ledger_kind].some((item) => item.key === site.key))
            locations[row.ledger_kind].push(site);
      return success(
        {
          locations,
          permissions: context.session.permissions.filter((key) => key.startsWith("inventory.audit.")),
          capabilities: {
            serial_registry: false,
            on_hand: true,
            managed_options: true,
            offline_counts: true,
          },
        },
        true,
      );
    }
    if (request.path === auditBase) {
      const rows = this.store
        .all("SELECT id FROM audit_sessions WHERE scope=? AND permissions=? ORDER BY id DESC", [
          scope(context),
          permissions(context),
        ])
        .map((row) => this.session(context, Number(row.id)))
        .filter((row): row is AuditSession => row !== null);
      return success(this.page(rows, request.query, 25), true);
    }
    if (!match) return unavailable();
    const id = Number(match[1]),
      row = this.session(context, id);
    if (!row) return unavailable();
    if (!match[2]) return success(row, true);
    const records = this.records(context, id),
      items = records.map((record) => auditLineSchema.parse(JSON.parse(String(record.body))));
    if (match[2] === "/lines") {
      const q = String(request.query?.q ?? "").toLocaleLowerCase(),
        location = request.query?.location_key,
        status = request.query?.status;
      const counted = request.query?.counted;
      const filtered = items.filter(
        (line) =>
          (!location || line.location_key === location) &&
          (!q ||
            (request.query?.exact
              ? [
                  line.product.sku,
                  line.product.barcode,
                  line.product.current_sku ?? "",
                  line.product.current_barcode ?? "",
                  String(line.product.id),
                ].some((value) => value.toLocaleLowerCase() === q)
              : [
                  line.product.name,
                  line.product.sku,
                  line.product.barcode,
                  line.product.model,
                  line.product.variant_name,
                ].some((value) => value.toLocaleLowerCase().includes(q)))) &&
          (counted === undefined || (String(counted) === "true") === (line.counted_quantity !== null)) &&
          (!status ||
            status === "all" ||
            (status === "unreviewed" && line.resolution === "unreviewed" && line.counted_quantity !== null) ||
            line.status === status),
      );
      return success(this.page(filtered, request.query, 30), true);
    }
    const detail = match[2]?.match(/^\/lines\/(\d+)\/details$/);
    if (detail) {
      const line = items.find((item) => item.id === Number(detail[1]));
      return line ? success({ line }, true) : unavailable();
    }
    if (match[2] === "/history") {
      const data = this.store
        .all("SELECT * FROM audit_local_history WHERE scope=? AND session_id=? ORDER BY id DESC", [
          scope(context),
          id,
        ])
        .filter((item) => !request.query?.line_id || Number(request.query.line_id) === Number(item.line_id))
        .map((item) => ({
          id: Number(item.id),
          line_id: item.line_id,
          action: String(item.action),
          actor_id: context.session.user.id,
          actor_name: context.session.user.name,
          created_at: new Date(Number(item.created)).toISOString(),
          detail: JSON.parse(String(item.detail)),
        }));
      return success(this.page(data, request.query, 30), true);
    }
    return unavailable();
  }
  private page<T>(items: T[], query: FinoraRequest["query"], defaultSize: number) {
    const rawPage = Number(query?.page ?? 1),
      rawSize = Number(query?.page_size ?? defaultSize);
    const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
      size = Number.isSafeInteger(rawSize) && rawSize > 0 && rawSize <= 100 ? rawSize : defaultSize;
    return {
      items: items.slice((page - 1) * size, page * size),
      page,
      page_size: size,
      total: items.length,
      total_pages: Math.max(1, Math.ceil(items.length / size)),
    };
  }
  private async send(input: FinoraRequest, sender: Sender): Promise<FinoraResponse> {
    const context = this.localContext();
    if (!context) return { ok: false, failure: "unauthenticated" };
    let request = finoraRequestSchema.parse(input);
    if (request.query || !request.body || typeof request.body !== "object" || Array.isArray(request.body))
      return reject("طلب الجرد غير صالح", 400);
    const body = request.body,
      key = z.string().uuid().safeParse(body.idempotency_key);
    if (!key.success) return reject("معرف عملية الجرد غير صالح", 400);
    if (body.audit_context && canonical(body.audit_context) !== canonical(auditContext(context.session)))
      return reject("طلب الجرد يعود لشركة أو موظف أو فرع مختلف", 403);
    request = { ...request, body: { ...body, audit_context: auditContext(context.session) } };
    const action = request.path === auditBase ? "create" : String(body.action);
    if (!permissionFor[action] || !allowed(context, action))
      return reject("ليست لديك صلاحية هذا الإجراء", 403);
    const id = request.path === auditBase ? null : Number(request.path.split("/")[5]),
      lineId = typeof body.line_id === "number" ? body.line_id : null;
    const own = scope(context),
      target = `${id ?? "create"}:${lineId ?? "session"}`;
    if (action === "begin_count" && (this.forceOffline() || this.disconnected))
      return this.beginLocal(context, id, lineId, body.version);
    if (action === "cancel_count" && typeof body.ticket === "string" && this.tickets.has(body.ticket)) {
      this.tickets.delete(body.ticket);
      return success({ session_id: id, line_id: lineId, version: body.version }, true);
    }
    const ticket = typeof body.ticket === "string" ? this.tickets.get(body.ticket) : undefined;
    if (action === "save_count" && ticket) {
      request = {
        ...request,
        body: {
          ...body,
          audit_context: auditContext(context.session),
          action: "save_offline_count",
          counted_at: new Date(this.now()).toISOString(),
        },
      };
      return this.queueCount(context, request, ticket);
    }
    const offline = this.forceOffline() || this.disconnected;
    if (offline) return reject("هذا الإجراء يحتاج اتصالاً حياً؛ مزامن العد المحلي أولاً", 409);
    const verified = await this.verify(context, sender);
    if (verified) return verified;
    const current = this.localContext();
    if (!current || scope(current) !== own || !allowed(current, action))
      return reject("تغيّرت صلاحيات الموظف", 403);
    if (
      action === "prepare_offline" &&
      this.store.one(
        "SELECT key FROM audit_commands WHERE scope=? AND session_id=? AND action='save_offline_count'",
        [own, id],
      )
    )
      return reject("زامن العد المحلي أو راجع تعارضه قبل استبدال لقطته");
    if (
      ["submit", "pause", "resume", "reopen", "approve", "post", "transfer_draft"].includes(action) &&
      this.store.one("SELECT key FROM audit_commands WHERE scope=? AND session_id=? AND key!=?", [
        own,
        id,
        key.data,
      ])
    )
      return reject("راجع العمليات المحلية لهذه الجلسة وزامنها قبل المراجعة والترحيل");
    const payload = JSON.stringify(request),
      fingerprint = digest(canonical(request));
    if (Buffer.byteLength(payload) > 256_000) return reject("طلب الجرد أكبر من الحد المسموح", 400);
    const previous = this.store.one("SELECT * FROM audit_commands WHERE scope=? AND key=?", [own, key.data]);
    if (previous && previous.fingerprint !== fingerprint)
      return reject("لا تغيّر بيانات عملية محفوظة؛ استرجع الطلب الأصلي");
    if (previous?.state === "confirmed" && previous.reply) return this.safeReply(previous, current);
    if (
      !previous &&
      this.store.one("SELECT key FROM audit_commands WHERE scope=? AND target=?", [own, target])
    )
      return reject("يوجد طلب محفوظ لهذا الصنف؛ راجعه قبل إنشاء طلب آخر");
    if (!previous)
      await this.store.write(() =>
        this.store.run(
          "INSERT INTO audit_commands(scope,key,path,target,session_id,line_id,action,payload,fingerprint,created,state) VALUES(?,?,?,?,?,?,?,?,?,?,'uncertain')",
          [own, key.data, request.path, target, id, lineId, action, payload, fingerprint, this.now()],
        ),
      );
    return this.dispatch(request, own, key.data, sender, !previous);
  }
  private async beginLocal(
    context: Context,
    id: number | null,
    lineId: number | null,
    version: unknown,
  ): Promise<FinoraResponse> {
    if (!id || !lineId || !allowed(context, "count")) return unavailable();
    const row = this.session(context, id),
      record = this.store.one(
        "SELECT * FROM audit_records WHERE scope=? AND session_id=? AND line_id=? AND permissions=?",
        [scope(context), id, lineId, permissions(context)],
      );
    if (!row || row.status !== "counting" || !record) return unavailable();
    if (this.now() - Date.parse(String(record.issued)) > 24 * 60 * 60_000)
      return reject("لقطة الجرد انتهت؛ نزّل لقطة جديدة وأعد العد");
    if (
      this.store.one("SELECT key FROM audit_commands WHERE scope=? AND target=? AND state!='pending'", [
        scope(context),
        `${id}:${lineId}`,
      ])
    )
      return reject("هذه العملية تحتاج حسم المزامنة أولاً؛ لا تستبدل نتيجة غير مؤكدة");
    const line = auditLineSchema.parse(JSON.parse(String(record.body)));
    if (line.version !== version) return reject("حدّث بطاقة الصنف قبل العد");
    const data = {
      line,
      ticket: String(record.ticket),
      version: Number(record.version),
      ...(context.session.permissions.includes("inventory.audit.system")
        ? { expected: line.current_quantity ?? line.expected_quantity ?? line.baseline_quantity ?? undefined }
        : {}),
    };
    this.tickets.set(data.ticket, data);
    return success(
      {
        session_id: id,
        line_id: lineId,
        version: data.version,
        ticket: data.ticket,
        started_at: String(record.issued),
        expected_quantity: data.expected,
      },
      true,
    );
  }
  private async queueCount(
    context: Context,
    request: FinoraRequest,
    ticket: { line: AuditLine; ticket: string; version: number; expected?: number },
  ): Promise<FinoraResponse> {
    const body = request.body as Record<string, unknown>,
      quantity = body.quantity,
      notes = body.notes ?? "";
    if (
      typeof quantity !== "number" ||
      !Number.isSafeInteger(quantity) ||
      quantity < 0 ||
      quantity > 1_000_000_000 ||
      typeof notes !== "string" ||
      notes.length > 2000
    )
      return reject("أدخل عدداً صحيحاً وملاحظة ضمن الحد المسموح", 400);
    const own = scope(context),
      id = Number(request.path.split("/")[5]),
      lineId = ticket.line.id,
      target = `${id}:${lineId}`,
      key = String(body.idempotency_key);
    if (
      this.store.one("SELECT key FROM audit_commands WHERE scope=? AND target=? AND state!='pending'", [
        own,
        target,
      ])
    )
      return reject("حُسم إرسال هذه العملية؛ أكّد نتيجتها قبل أي تعديل محلي");
    const liveContext = this.localContext();
    if (!liveContext || scope(liveContext) !== own || !allowed(liveContext, "count"))
      return { ok: false, failure: "unauthenticated" };
    if (body.ticket !== ticket.ticket || body.version !== ticket.version || body.line_id !== lineId)
      return reject("تذكرة العد المحلي غير صالحة");
    await this.store.write(() => {
      this.store.run("DELETE FROM audit_commands WHERE scope=? AND target=? AND state='pending'", [
        own,
        target,
      ]);
      this.store.run(
        "INSERT INTO audit_commands(scope,key,path,target,session_id,line_id,action,payload,fingerprint,created,state) VALUES(?,?,?,?,?,?,'save_offline_count',?,?,?,'pending')",
        [
          own,
          key,
          request.path,
          target,
          id,
          lineId,
          JSON.stringify(request),
          digest(canonical(request)),
          this.now(),
        ],
      );
      const line = {
        ...ticket.line,
        counted_quantity: quantity,
        notes,
        counted_at: new Date(this.now()).toISOString(),
        counted_by: context.session.user.id,
        expected_quantity: ticket.expected ?? null,
        difference: ticket.expected === undefined ? null : quantity - ticket.expected,
        status:
          ticket.expected === undefined
            ? "counted"
            : quantity < ticket.expected
              ? "shortage"
              : quantity > ticket.expected
                ? "surplus"
                : "matched",
        resolution: "unreviewed",
        resolution_note: "",
        reviewed_at: null,
        reviewed_by: null,
      };
      this.store.run("UPDATE audit_records SET body=? WHERE scope=? AND session_id=? AND line_id=?", [
        JSON.stringify(line),
        own,
        id,
        lineId,
      ]);
      this.store.run(
        "INSERT INTO audit_local_history(scope,session_id,line_id,action,created,detail) VALUES(?,?,?,'save_offline_count',?,?)",
        [
          own,
          id,
          lineId,
          this.now(),
          JSON.stringify({ before: ticket.line.counted_quantity, after: quantity, notes, offline: true }),
        ],
      );
    });
    this.tickets.delete(ticket.ticket);
    return success({ session_id: id, line_id: lineId, version: ticket.version, queued: true }, true);
  }
  private async dispatch(
    request: FinoraRequest,
    own: string,
    key: string,
    sender: Sender,
    firstAttempt = false,
  ): Promise<FinoraResponse> {
    const active = this.localContext();
    if (!active || scope(active) !== own) return { ok: false, failure: "unauthenticated" };
    const result = await sender(request),
      body = request.body as Record<string, unknown>,
      parsed = result.ok
        ? z
            .object({
              success: z.literal(true),
              data: auditReceiptSchema(request.path === auditBase ? "create" : String(body.action)),
            })
            .safeParse(result.data)
        : null,
      prepared = result.ok ? snapshot.safeParse(result.data) : null;
    const preparedContext = this.localContext();
    const requestedLines = Array.isArray(body.line_ids)
      ? [...new Set(body.line_ids)].sort((a, b) => Number(a) - Number(b))
      : [];
    const preparedMatches =
      prepared?.success &&
      preparedContext &&
      scope(preparedContext) === own &&
      prepared.data.data.snapshot.id === prepared.data.data.session_id &&
      JSON.stringify(prepared.data.data.snapshot_permissions) ===
        JSON.stringify(
          ["inventory.audit.system", "inventory.audit.cost"].filter((name) =>
            preparedContext.session.permissions.includes(
              name as (typeof preparedContext.session.permissions)[number],
            ),
          ),
        ) &&
      JSON.stringify(prepared.data.data.records.map((record) => record.line.id).sort((a, b) => a - b)) ===
        JSON.stringify(requestedLines) &&
      prepared.data.data.records.every(
        (record) =>
          record.version === record.line.version &&
          prepared.data.data.snapshot.locations.some((location) => location.key === record.line.location_key),
      );
    if (
      !result.ok &&
      (result.status === 401 || result.status === 403 || result.failure === "unauthenticated")
    )
      await this.deactivate();
    if (
      result.ok &&
      parsed?.success &&
      (request.path === auditBase || parsed.data.data.session_id === Number(request.path.split("/")[5])) &&
      (body.line_id === undefined || parsed.data.data.line_id === body.line_id) &&
      (body.action !== "prepare_offline" || preparedMatches)
    ) {
      await this.store.write(() => {
        this.store.run(
          "UPDATE audit_commands SET state='confirmed',error=NULL,reply=? WHERE scope=? AND key=?",
          [JSON.stringify(result), own, key],
        );
        const current = this.localContext();
        if (prepared?.success && current && scope(current) === own) {
          const data = prepared.data.data,
            p = permissions(current);
          this.store.run("INSERT OR REPLACE INTO audit_sessions(scope,id,body,permissions) VALUES(?,?,?,?)", [
            own,
            data.session_id,
            JSON.stringify(data.snapshot),
            p,
          ]);
          for (const record of data.records) {
            const line = { ...record.line, current_quantity: record.expected_quantity ?? null };
            this.store.run(
              "INSERT OR REPLACE INTO audit_records(scope,session_id,line_id,body,ticket,version,issued,permissions) VALUES(?,?,?,?,?,?,?,?)",
              [
                own,
                data.session_id,
                line.id,
                JSON.stringify(line),
                record.ticket,
                record.version,
                record.issued_at,
                p,
              ],
            );
          }
        }
        if (body.action === "save_offline_count")
          this.store.run("DELETE FROM audit_records WHERE scope=? AND session_id=? AND line_id=?", [
            own,
            parsed.data.data.session_id,
            Number(body.line_id),
          ]);
      });
      const afterWrite = this.localContext();
      if (!afterWrite || scope(afterWrite) !== own) return { ok: false, failure: "unauthenticated" };
      return { ...result, auditCommandScope: own, auditCommandPath: request.path };
    }
    const explicit = !result.ok && result.failure === "http" && [400, 404, 409, 422].includes(result.status);
    const queued = body.action === "save_offline_count";
    await this.store.write(() => {
      if (explicit && firstAttempt && !queued)
        this.store.run("DELETE FROM audit_commands WHERE scope=? AND key=?", [own, key]);
      else
        this.store.run("UPDATE audit_commands SET state=?,error=? WHERE scope=? AND key=?", [
          explicit && queued ? "conflict" : "uncertain",
          !result.ok &&
          result.failure === "http" &&
          typeof result.data === "object" &&
          result.data &&
          "error" in result.data
            ? String(result.data.error)
            : "لم يصل تأكيد الخادم؛ أعد نفس الطلب",
          own,
          key,
        ]);
    });
    return result.ok ? { ok: false, failure: "invalid_response" } : result;
  }
  private safeReply(row: Record<string, import("sql.js").SqlValue>, context: Context): FinoraResponse {
    const result = JSON.parse(String(row.reply)) as FinoraResponse;
    if (!result.ok) return result;
    const parsed = receipt.safeParse(result.data);
    if (!parsed.success) return { ok: false, failure: "invalid_response" };
    const body = result.data as { success: true; data: Record<string, unknown> };
    if (row.action === "prepare_offline") {
      const prepared = snapshot.safeParse(result.data);
      const granted = ["inventory.audit.system", "inventory.audit.cost"].filter((permission) =>
        context.session.permissions.some((key) => key === permission),
      );
      if (
        !prepared.success ||
        JSON.stringify(prepared.data.data.snapshot_permissions) !== JSON.stringify(granted)
      )
        return reject("تغيّرت صلاحيات لقطة التنزيل؛ لا تعرض بيانات الصلاحية السابقة");
    }
    if (row.action === "begin_count" && !context.session.permissions.includes("inventory.audit.system"))
      delete body.data.expected_quantity;
    return { ...result, data: body, auditCommandScope: scope(context), auditCommandPath: String(row.path) };
  }
  private async localAction(input: FinoraRequest, sender: Sender): Promise<FinoraResponse> {
    const parsed = auditLocalAction.safeParse(input.body),
      context = this.localContext();
    if (!parsed.success) return reject("إجراء استرجاع الجرد غير صالح", 400);
    if (!context) return { ok: false, failure: "unauthenticated" };
    const data = parsed.data,
      own = scope(context),
      row = this.store.one("SELECT * FROM audit_commands WHERE scope=? AND key=?", [own, data.key]);
    if (!row || !allowed(context, String(row.action))) return reject("طلب الجرد غير موجود ضمن صلاحياتك", 404);
    if (data.operation === "ack") {
      if (data.scope !== own || data.path !== row.path || row.state !== "confirmed")
        return reject("تأكيد الطلب لا يطابق المصدر");
      await this.store.write(() =>
        this.store.run("DELETE FROM audit_commands WHERE scope=? AND key=? AND state='confirmed'", [
          own,
          data.key,
        ]),
      );
      return success({ acknowledged: true });
    }
    if (data.operation === "discard") {
      if (!["pending", "conflict"].includes(String(row.state)))
        return reject("لا يمكن إسقاط طلب بنتيجة غير مؤكدة؛ أكده أولاً");
      await this.store.write(() => {
        this.store.run(
          "INSERT INTO audit_local_history(scope,session_id,line_id,action,created,detail) VALUES(?,?,?,'discard_offline_count',?,?)",
          [
            own,
            Number(row.session_id),
            row.line_id ?? null,
            this.now(),
            JSON.stringify({ reason: data.reason, key: data.key }),
          ],
        );
        this.store.run("DELETE FROM audit_records WHERE scope=? AND session_id=? AND line_id=?", [
          own,
          Number(row.session_id),
          row.line_id ?? null,
        ]);
        this.store.run("DELETE FROM audit_commands WHERE scope=? AND key=?", [own, data.key]);
      });
      return success({ discarded: true });
    }
    const verified = await this.verify(context, sender, true);
    if (verified) return verified;
    const current = this.localContext();
    if (!current || scope(current) !== own || !allowed(current, String(row.action)))
      return reject("تغيّرت الصلاحيات", 403);
    if (row.state === "confirmed" && row.reply) return this.safeReply(row, current);
    // Durable transition before network dispatch prevents editing a payload whose result is unknown.
    await this.store.write(() =>
      this.store.run("UPDATE audit_commands SET state='uncertain' WHERE scope=? AND key=?", [own, data.key]),
    );
    return this.dispatch(finoraRequestSchema.parse(JSON.parse(String(row.payload))), own, data.key, sender);
  }
}
