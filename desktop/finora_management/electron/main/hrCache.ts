import { z } from "zod";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
import type { FinoraSession } from "../../src/api/finora/schemas";
import { OfflineDatabase } from "./offlineDatabase";
import { hrOperationSchema } from "../../shared/hrOffline";
const record = z.record(z.unknown());
const revisionSchema = z.object({ revision: z.string().min(1), scope_revision: z.string().min(1) });
const pageSchema = z.object({
  rows: z.array(record),
  page: z.number(),
  page_size: z.number(),
  total: z.number(),
  total_pages: z.number(),
});
const bundleSchema = z.object({
  people: z.array(record),
  details: z.record(record),
  lookups: record,
  overview: record,
  workspaces: z.record(z.array(record)),
  startedAt: z.number().optional(),
});
type Bundle = z.infer<typeof bundleSchema>;
type Context = { id: string; session: FinoraSession };
function baghdadToday(now: number) {
  return new Date(now + 3 * 3600000).toISOString().slice(0, 10);
}
export class HRCache {
  constructor(
    private store: OfflineDatabase,
    private context: () => Context | null,
    private sender: (request: FinoraRequest) => Promise<FinoraResponse>,
    private now: () => number = Date.now,
  ) {}
  status() {
    const context = this.context(),
      row =
        context && this.store.one("SELECT saved,stale,body FROM hr_snapshots WHERE scope=?", [context.id]);
    if (!row) return { ready: false, people: 0, savedAt: null, stale: false };
    return {
      ready: true,
      people: bundleSchema.parse(JSON.parse(String(row.body))).people.length,
      savedAt: Number(row.saved),
      stale: !!row.stale,
    };
  }
  query(request: FinoraRequest): { data: unknown; saved: number } | null {
    const context = this.context(),
      row = context && this.store.one("SELECT saved,body FROM hr_snapshots WHERE scope=?", [context.id]);
    if (!context || !row || request.method !== "GET" || !request.path.startsWith("/hr/api/")) return null;
    const bundle = bundleSchema.parse(JSON.parse(String(row.body))),
      args = request.query ?? {};
    let saved = Number(row.saved);
    const pending = this.store.all(
      "SELECT rowid AS local_id,payload,created,status,invoice FROM operations WHERE scope=? AND status IN ('pending','syncing','done') ORDER BY created,rowid",
      [context.id],
    );
    for (const operation of pending) {
      const parsed = hrOperationSchema.safeParse(JSON.parse(String(operation.payload)));
      if (!parsed.success) continue;
      if (
        operation.status === "done" &&
        (!parsed.data.acknowledgedAt || parsed.data.acknowledgedAt <= (bundle.startedAt ?? Number(row.saved)))
      )
        continue;
      const payload = parsed.data.command.payload,
        id = Number(payload.person_id),
        detail = bundle.details[String(id)],
        profile = bundle.people.find((p) => p.id === id);
      if (parsed.data.command.action === "employee.update" && detail && profile) {
        if (operation.status === "done" && operation.invoice) {
          const receipt = record.parse(JSON.parse(String(operation.invoice)));
          if (Number(receipt.version ?? 0) <= Number(profile.version ?? 0)) continue;
        } else if (Number(payload.version) < Number(profile.version ?? 0)) continue;
        const changes = Object.fromEntries(
          Object.entries(payload).filter(([key]) =>
            [
              "name",
              "code",
              "phone",
              "phone2",
              "email",
              "address",
              "emergency_name",
              "emergency_phone",
              "notes",
              "job_title",
              "department_id",
            ].includes(key),
          ),
        );
        Object.assign(profile, changes, { pending: operation.status !== "done" });
        const personal = record.safeParse(detail.person);
        if (personal.success) Object.assign(personal.data, changes);
        if (personal.success) detail.person = personal.data;
        if (operation.status === "done" && operation.invoice) {
          const receipt = record.parse(JSON.parse(String(operation.invoice)));
          profile.version = receipt.version ?? profile.version;
          if (personal.success) personal.data.version = profile.version;
        }
        saved = Math.max(
          saved,
          parsed.data.acknowledgedAt ?? parsed.data.modifiedAt ?? Number(operation.created),
        );
        continue;
      }
      if (["leave.request", "resource.record"].includes(parsed.data.command.action) && profile) {
        const key = parsed.data.command.action === "leave.request" ? "leave" : "resources";
        const rows = bundle.workspaces[key];
        const receipt =
          operation.status === "done" && operation.invoice
            ? record.parse(JSON.parse(String(operation.invoice)))
            : null;
        const localId = receipt?.id ?? -Number(operation.local_id);
        if (rows && !rows.some((r) => r.id === localId)) {
          const entry: Record<string, unknown> = {
            id: localId,
            person_id: id,
            person_name: profile.name,
            code: profile.code,
            pending: operation.status !== "done",
          };
          if (key === "leave") {
            const kinds = bundle.lookups.leave_types as Record<string, unknown>[] | undefined;
            Object.assign(entry, {
              type: kinds?.find((k) => k.id === payload.type_id)?.name ?? "إجازة",
              starts: payload.starts,
              ends: payload.ends,
              reason: payload.reason ?? "",
              status: receipt ? "pending" : "queued",
              days: payload.half_day ? 0.5 : undefined,
              version: 1,
            });
          } else
            Object.assign(entry, {
              kind: payload.kind,
              date: new Date(Number(operation.created)).toISOString(),
              detail: {
                title: payload.title,
                note: payload.note ?? "",
                period: payload.period ?? "",
                score: payload.score,
              },
            });
          rows.unshift(entry);
          saved = Math.max(
            saved,
            parsed.data.acknowledgedAt ?? parsed.data.modifiedAt ?? Number(operation.created),
          );
        }
        continue;
      }
      if (parsed.data.command.action !== "attendance.record") continue;
      if (!detail || !profile || typeof payload.occurred_at !== "string") continue;
      const local = new Date(new Date(payload.occurred_at).getTime() + 3 * 3600000).toISOString();
      const current = record.safeParse(detail.attendance);
      const previous = current.success ? current.data : null;
      let attendance: Record<string, unknown>;
      if (payload.event === "check_in") {
        let date = local.slice(0, 10);
        const shift =
          previous?.shift && typeof previous.shift === "object"
            ? (previous.shift as Record<string, unknown>)
            : null;
        if (
          shift &&
          typeof shift.starts === "string" &&
          typeof shift.ends === "string" &&
          shift.ends <= shift.starts &&
          local.slice(11, 16) <= shift.ends
        )
          date = new Date(new Date(date + "T12:00:00Z").getTime() - 86400000).toISOString().slice(0, 10);
        attendance = {
          id: null,
          date,
          state: "present",
          check_in: local.slice(11, 16),
          check_out: "",
          check_in_at: payload.occurred_at,
          check_out_at: null,
          worked_minutes: 0,
          late_minutes: 0,
          overtime_minutes: 0,
          early_minutes: 0,
          version: 0,
          shift,
          pending: operation.status !== "done",
        };
      } else if (previous && previous.check_in) {
        const start = typeof previous.check_in_at === "string" ? Date.parse(previous.check_in_at) : NaN;
        const shift =
          previous.shift && typeof previous.shift === "object"
            ? (previous.shift as Record<string, unknown>)
            : null;
        attendance = {
          ...previous,
          check_out: local.slice(11, 16),
          check_out_at: payload.occurred_at,
          worked_minutes: Number.isFinite(start)
            ? Math.max(
                0,
                Math.floor((Date.parse(payload.occurred_at) - start) / 60000) -
                  Number(shift?.break_minutes ?? 0),
              )
            : previous.worked_minutes,
          pending: operation.status !== "done",
        };
      } else continue;
      if (operation.status === "done" && operation.invoice) {
        const receipt = record.parse(JSON.parse(String(operation.invoice)));
        const confirmed = record.safeParse(receipt.attendance);
        if (confirmed.success) attendance = { ...confirmed.data, pending: false };
        else
          Object.assign(attendance, {
            id: receipt.id ?? attendance.id,
            version: receipt.version ?? attendance.version,
          });
      }
      detail.attendance = attendance;
      profile.attendance = attendance;
      const rows = bundle.workspaces[`attendance:${String(attendance.date)}`];
      const workspace = rows?.find((r) => r.person_id === id);
      if (workspace) Object.assign(workspace, attendance);
      else if (rows)
        rows.push({ ...attendance, person_id: id, person_name: profile.name, code: profile.code });
      saved = Math.max(
        saved,
        parsed.data.acknowledgedAt ?? parsed.data.modifiedAt ?? Number(operation.created),
      );
    }
    const pagination = (rows: Record<string, unknown>[]) => {
      const page = Math.max(1, Number(args.page) || 1),
        size = Math.min(100, Math.max(1, Number(args.page_size) || 25));
      return {
        rows: rows.slice((page - 1) * size, page * size),
        page,
        page_size: size,
        total: rows.length,
        total_pages: Math.max(1, Math.ceil(rows.length / size)),
      };
    };
    let people = bundle.people.filter(
      (p) =>
        (!args.status || p.status === args.status) &&
        (!args.branch_id || String(p.branch_id) === String(args.branch_id)) &&
        (!args.department_id || String(p.department_id) === String(args.department_id)) &&
        (!args.contract_type || p.contract_type === args.contract_type),
    );
    if (args.search) {
      const term = String(args.search).toLocaleLowerCase();
      people = people.filter((p) =>
        ["name", "phone", "code", "email", "department", "job_title"].some((k) =>
          String(p[k] ?? "")
            .toLocaleLowerCase()
            .includes(term),
        ),
      );
    }
    let data: unknown;
    if (request.path === "/hr/api/page") {
      people.sort((a, b) =>
        args.sort === "recent"
          ? String(b.updated_at).localeCompare(String(a.updated_at))
          : String(a[args.sort === "code" ? "code" : "name"]).localeCompare(
              String(b[args.sort === "code" ? "code" : "name"]),
              "ar",
            ),
      );
      data = pagination(people);
    } else if (request.path === "/hr/api/lookups") data = bundle.lookups;
    else if (request.path === "/hr/api/overview") data = bundle.overview;
    else if (/^\/hr\/api\/people\/\d+$/.test(request.path))
      data = bundle.details[request.path.split("/").at(-1) ?? ""];
    else if (request.path === "/hr/api/workspace") {
      const tab = String(args.tab ?? "attendance"),
        date = String(args.date ?? baghdadToday(this.now())),
        month = String(args.month ?? baghdadToday(this.now()).slice(0, 7));
      const key = tab === "attendance" ? `${tab}:${date}` : tab === "payroll" ? `${tab}:${month}` : tab;
      const cached = bundle.workspaces[key];
      if (!cached) return null;
      const ids = new Set(people.map((p) => p.id));
      data = pagination(
        cached.filter(
          (r) => ids.has(r.person_id) && (!args.person_id || String(r.person_id) === String(args.person_id)),
        ),
      );
    }
    return data === undefined ? null : { data, saved };
  }
  async download() {
    const context = this.context();
    if (!context || !context.session.permissions.some((p) => ["hr.view", "hr.self"].includes(p))) return;
    const identity = JSON.stringify([context.session.permissions, context.session.hr_scope_revision]),
      bundle: Bundle = {
        people: [],
        details: {},
        lookups: {},
        overview: {},
        workspaces: {},
        startedAt: this.now(),
      };
    const get = async (request: FinoraRequest) => {
      const response = await this.sender(request),
        current = this.context();
      if (
        !response.ok ||
        !current ||
        current.id !== context.id ||
        JSON.stringify([current.session.permissions, current.session.hr_scope_revision]) !== identity
      )
        throw new Error(
          "تعذّر تنزيل بيانات الموارد البشرية أو تغيّر نطاق الصلاحيات؛ بقيت النسخة السابقة محفوظة",
        );
      return response.data;
    };
    const start = revisionSchema.parse(await get({ method: "GET", path: "/hr/api/offline/revision" }));
    const sameRevision = (value: z.infer<typeof revisionSchema>) =>
      value.revision === start.revision && value.scope_revision === start.scope_revision;
    for (let page = 1; ; page++) {
      const part = z
        .object({
          directory: pageSchema,
          details: z.array(record),
          lookups: record.optional(),
          overview: record.optional(),
          revision: z.string(),
          scope_revision: z.string(),
        })
        .parse(
          await get({
            method: "GET",
            path: "/hr/api/offline",
            query: { page, page_size: 100 },
            timeoutMs: 60000,
          }),
        );
      if (!sameRevision(part))
        throw new Error("تغيّرت بيانات الموارد البشرية أثناء التنزيل؛ أعد المزامنة للحصول على نسخة متناسقة");
      bundle.people.push(...part.directory.rows);
      for (const detail of part.details) {
        const person = record.parse(detail.person);
        bundle.details[String(person.id)] = detail;
      }
      if (part.lookups) bundle.lookups = part.lookups;
      if (part.overview) bundle.overview = part.overview;
      if (page >= part.directory.total_pages) break;
      if (page >= 1000) throw new Error("بيانات الموارد البشرية تتجاوز حجم التنزيل المسموح");
    }
    const has = (p: string) => context.session.permissions.some((value) => value === p),
      self = has("hr.self"),
      requests: { tab: string; key: string; query: Record<string, string> }[] = [];
    if (has("hr.attendance.view") || self)
      for (let i = 0; i < 8; i++) {
        const date = baghdadToday(this.now() - i * 86400000);
        requests.push({ tab: "attendance", key: `attendance:${date}`, query: { date } });
      }
    if (has("hr.payroll.view") || self)
      for (let i = 0; i < 3; i++) {
        const on = new Date(`${baghdadToday(this.now()).slice(0, 7)}-01T12:00:00Z`);
        on.setUTCMonth(on.getUTCMonth() - i);
        const month = on.toISOString().slice(0, 7);
        requests.push({ tab: "payroll", key: `payroll:${month}`, query: { month } });
      }
    for (const [tab, permission] of [
      ["leave", "hr.leave.manage"],
      ["advances", "hr.advance.view"],
      ["resources", "hr.resources.manage"],
      ["commissions", "hr.commission.view"],
    ])
      if (
        permission &&
        (has(permission) || (self && ["leave", "advances", "commissions"].includes(tab ?? ""))) &&
        tab
      )
        requests.push({ tab, key: tab, query: {} });
    for (const item of requests) {
      const rows: Record<string, unknown>[] = [];
      for (let page = 1; ; page++) {
        const part = pageSchema.parse(
          await get({
            method: "GET",
            path: "/hr/api/workspace",
            query: { tab: item.tab, ...item.query, page, page_size: 100 },
            timeoutMs: 60000,
          }),
        );
        rows.push(...part.rows);
        if (page >= part.total_pages) break;
        if (page >= 1000) throw new Error("عدد سجلات الموارد البشرية يتجاوز الحد المسموح");
      }
      bundle.workspaces[item.key] = rows;
    }
    if (!sameRevision(revisionSchema.parse(await get({ method: "GET", path: "/hr/api/offline/revision" }))))
      throw new Error("تغيّرت بيانات الموارد البشرية أثناء التنزيل؛ بقيت النسخة السابقة محفوظة");
    await this.store.write(() => {
      const current = this.context();
      if (
        !current ||
        current.id !== context.id ||
        JSON.stringify([current.session.permissions, current.session.hr_scope_revision]) !== identity
      )
        throw new Error("تغيّر نطاق بيانات الموارد البشرية أثناء التنزيل");
      this.store.run("INSERT OR REPLACE INTO hr_snapshots VALUES (?,?,?,0)", [
        context.id,
        JSON.stringify(bundle),
        this.now(),
      ]);
    });
  }
}
