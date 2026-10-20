import { createHash, randomUUID } from "node:crypto";
import { z } from "zod";
import { finoraRequestSchema, type FinoraRequest, type FinoraResponse } from "../../shared/ipc";
import {
  hrCommandSchema,
  hrOperationSchema,
  offlineHRAllowed,
  HR_ACTION_LABELS,
} from "../../shared/hrOffline";
import {
  supplierDraftSchema,
  posSaleSchema,
  type PosSale,
  type OfflineOperation,
  type OfflineStatus,
  type SupplierDraft,
} from "../../shared/offline";
import { sessionEnvelopeSchema, type FinoraSession } from "../../src/api/finora/schemas";
import { pendingLocalWork } from "./portableStore";
import { OfflineDatabase } from "./offlineDatabase";
import { OfflineSnapshot } from "./offlineSnapshot";
import { snapshotQuery } from "./snapshotQueries";
import { OfflineStock } from "./offlineStock";
import { HRCache } from "./hrCache";
import { stockPartsSchema, type ReserveStock } from "../../shared/stock";
import { isCustomerCommand } from "../../shared/customerRecovery";
import { CustomerCommands } from "./customerCommands";
import { isStockCommand } from "../../shared/stockRecovery";
import { InventoryAudit } from "./inventoryAudit";
import { auditPath } from "../../shared/inventoryAudit";

type Sender = (request: FinoraRequest) => Promise<FinoraResponse>;
const SESSION_PATH = "/api/v1/desktop/auth/session";
const OFFLINE_LEASE_MS = 24 * 60 * 60_000;
const READ_PATH =
  /^\/(api\/v1\/desktop\/workspace\/(sales|receivables|activity|shipping)|api\/finance\/(meta|vouchers|loans|parties|notifications|vouchers\/\d+|loans\/\d+|parties\/(customer|supplier)\/\d+)|hr\/api\/(page|lookups|overview|workspace|calendar|people\/\d+)|orders\/(data|payment-accounts|api\/(counts|lookups)|details\/\d+)|inventory\/api\/(products(?:\/\d+)?|movements\/\d+)|purchases\/api\/(page|\d+|products\/search)|suppliers\/api\/(page|\d+|sale-products)|pos\/(api\/(bootstrap|products)|search-customer|payment-accounts))$/;

export function cacheKey(request: FinoraRequest): string {
  return JSON.stringify([
    request.path,
    Object.entries(request.query ?? {}).sort(([a], [b]) => a.localeCompare(b)),
  ]);
}
function identity(server: string, session: FinoraSession): string {
  return createHash("sha256")
    .update(
      JSON.stringify([
        server,
        session.tenant.slug,
        session.user.id,
        session.branch?.id ?? null,
        session.branch_scope ?? "branch",
      ]),
    )
    .digest("hex");
}
function connectivity(result: FinoraResponse): boolean {
  return !result.ok && (result.failure === "network" || result.failure === "timeout");
}

export class OfflineEngine {
  readonly customerCommands: CustomerCommands;
  readonly stockCommands: CustomerCommands;
  readonly inventoryAudit: InventoryAudit;
  private hr: HRCache;
  private snapshot: OfflineSnapshot;
  private stock: OfflineStock;
  private syncing: Promise<OfflineStatus> | null = null;
  private offline = false;
  private revoked = false;
  private error: string | null = null;
  constructor(
    private store: OfflineDatabase,
    private server: string,
    private sender: Sender,
    private now: () => number = Date.now,
  ) {
    this.inventoryAudit = new InventoryAudit(
      store,
      () => this.context(),
      async (session) => {
        await this.remember(session);
        this.offline = false;
      },
      () => this.deactivate(),
      () => this.offline,
      now,
    );
    this.customerCommands = new CustomerCommands(
      store,
      () => this.context(),
      now,
      (session) => this.remember(session),
      () => this.deactivate(),
    );
    this.stockCommands = new CustomerCommands(
      store,
      () => this.context(),
      now,
      (session) => this.remember(session),
      () => this.deactivate(),
      "stock",
    );
    this.hr = new HRCache(
      store,
      () => this.context(),
      async (request) => {
        const response = await sender(request);
        if (
          !response.ok &&
          (["unauthenticated", "password_change_required"].includes(response.failure) ||
            (response.failure === "http" && [401, 403].includes(response.status)))
        )
          await this.deactivate();
        return response;
      },
      now,
    );
    this.snapshot = new OfflineSnapshot(
      store,
      () => this.context(),
      async (request) => {
        const response = await sender(request);
        if (
          !response.ok &&
          (response.failure === "unauthenticated" ||
            response.failure === "password_change_required" ||
            response.status === 401 ||
            response.status === 403)
        )
          await this.deactivate();
        return response;
      },
    );
    this.stock = new OfflineStock(
      store,
      () => this.context(),
      async (request) => {
        const response = await sender(request);
        if (
          !response.ok &&
          (response.failure === "unauthenticated" ||
            response.failure === "password_change_required" ||
            response.status === 401 ||
            response.status === 403)
        )
          await this.deactivate();
        return response;
      },
    );
  }

  get serverUrl(): string {
    return this.server;
  }

  recordIssue(error: unknown): void {
    this.error = error instanceof Error ? error.message : "تعذّر حفظ بيانات الأوفلاين؛ راجع التخزين المحلي.";
  }
  private recoveringQuota: Promise<OfflineStatus> | null = null;
  reconcileRestoredQuota(): Promise<OfflineStatus> {
    if (!this.recoveringQuota)
      this.recoveringQuota = this.reconcileQuota().finally(() => {
        this.recoveringQuota = null;
      });
    return this.recoveringQuota;
  }
  private async reconcileQuota() {
    await this.store.settled();
    const context = this.context();
    if (
      !context ||
      !this.store.one("SELECT value FROM metadata WHERE key=?", [`restored-stock:${context.id}`]) ||
      pendingLocalWork(this.store, context.id)
    )
      return this.status();
    const device = String(this.store.one("SELECT value FROM metadata WHERE key='device'")?.value);
    const response = await this.sender({
      method: "GET",
      path: "/api/v1/desktop/stock/device",
      query: { device_id: device },
    });
    if (!response.ok || response.source === "offline") return this.status();
    const rowSchema = z
      .object({
        id: z.string().uuid(),
        grant_id: z.string().uuid(),
        product_id: z.number().int().positive(),
        name: z.string(),
        color: z.string(),
        quantity: z.number().int().nonnegative(),
        used: z.number().int().nonnegative(),
        returned: z.number().int().nonnegative(),
      })
      .refine((r) => r.used + r.returned <= r.quantity);
    const rows = z
      .object({ success: z.literal(true), allocations: z.array(rowSchema) })
      .parse(response.data).allocations;
    if (this.context()?.id !== context.id) throw Error("تغيّرت جلسة الدخول أثناء مراجعة الرصيد");
    await this.store.write(() => {
      if (this.context()?.id !== context.id || pendingLocalWork(this.store, context.id))
        throw Error("تغيّر سياق الاستعادة؛ أعد المزامنة بعد اكتمال العمليات");
      this.store.run("DELETE FROM device_stock WHERE scope=?", [context.id]);
      for (const row of rows)
        this.store.run(
          "INSERT INTO device_stock(id,scope,grant_id,product_id,name,color,quantity,used,returned,frozen) VALUES (?,?,?,?,?,?,?,?,?,1)",
          [
            row.id,
            context.id,
            row.grant_id,
            row.product_id,
            row.name,
            row.color,
            row.quantity,
            row.used,
            row.returned,
          ],
        );
    });
    const parts = rows
      .filter((r) => r.quantity > r.used + r.returned)
      .map((r) => ({ id: r.id, qty: r.quantity - r.used - r.returned }));
    if (parts.length) await this.stock.returnRecovered(parts);
    await this.store.write(() =>
      this.store.run("DELETE FROM metadata WHERE key=?", [`restored-stock:${context.id}`]),
    );
    return this.status();
  }
  backupContext() {
    const context = this.context();
    if (!context) throw Error("حدّث جلسة الدخول قبل نسخ البيانات المحلية");
    return context;
  }

  private context() {
    if (this.revoked) return null;
    const id = this.store.one("SELECT value FROM metadata WHERE key='active'")?.value;
    if (typeof id !== "string") return null;
    const row = this.store.one("SELECT * FROM contexts WHERE id=?", [id]);
    if (!row) return null;
    const session = sessionEnvelopeSchema.parse({ ok: true, session: JSON.parse(String(row.session)) });
    // A cached authorization belongs only to this server, tenant, user and branch.
    if (identity(this.server, session) !== id) return null;
    const verified = Number(row.verified);
    const age = this.now() - verified;
    if (age < 0 || age >= Math.min(OFFLINE_LEASE_MS, session.session_max_age_seconds * 1000)) return null;
    return { id, session, verified };
  }

  async deactivate(): Promise<void> {
    this.revoked = true;
    await this.store.write(() => this.store.run("DELETE FROM metadata WHERE key='active'"));
  }

  private async remember(session: FinoraSession): Promise<void> {
    const id = identity(this.server, session);
    const previous = this.store.one("SELECT session FROM contexts WHERE id=?", [id]);
    await this.store.write(() => {
      if (previous) {
        const old = JSON.parse(String(previous.session)) as FinoraSession;
        if (
          JSON.stringify(old.permissions.slice().sort()) !==
            JSON.stringify(session.permissions.slice().sort()) ||
          old.user.role !== session.user.role ||
          old.hr_scope_revision !== session.hr_scope_revision ||
          JSON.stringify(old.roles.slice().sort()) !== JSON.stringify(session.roles.slice().sort())
        ) {
          this.store.run("DELETE FROM responses WHERE scope=?", [id]);
          this.store.run("DELETE FROM snapshots WHERE scope=?", [id]);
          this.store.run("DELETE FROM snapshot_records WHERE scope=?", [id]);
          this.store.run("DELETE FROM hr_snapshots WHERE scope=?", [id]);
        }
      }
      this.store.run("INSERT OR REPLACE INTO contexts VALUES (?,?,?)", [
        id,
        JSON.stringify(session),
        this.now(),
      ]);
      this.store.run("INSERT OR REPLACE INTO metadata VALUES ('active',?)", [id]);
    });
    this.revoked = false;
  }

  async request(request: FinoraRequest, sender: Sender = this.sender): Promise<FinoraResponse> {
    if (auditPath.test(request.path)) return this.inventoryAudit.request(request, sender);
    if (isCustomerCommand(request)) return this.customerCommands.execute(request, sender);
    if (isStockCommand(request)) return this.stockCommands.execute(request, sender);
    if (request.method === "POST" && request.path === "/api/finance/commands")
      return this.financeCommand(request, sender);
    if (request.method === "POST" && request.path === "/hr/api/commands")
      return this.hrCommand(request, sender);
    const loggingIn = request.path === "/api/v1/desktop/auth/login";
    if (loggingIn) await this.deactivate();
    const context = this.context();
    const readable = request.method === "GET" && READ_PATH.test(request.path);
    const cached =
      context && readable
        ? this.store.one("SELECT body,saved FROM responses WHERE scope=? AND key=?", [
            context.id,
            cacheKey(request),
          ])
        : undefined;
    const frozen = context && readable ? snapshotQuery(this.snapshot, request) : undefined;
    const frozenAt = this.snapshot.active()?.manifest.captured_at ?? 0;
    let local =
      frozen !== undefined && (!cached || frozenAt >= Number(cached.saved))
        ? { body: JSON.stringify(frozen), saved: frozenAt }
        : cached;
    const hr = context && readable ? this.hr.query(request) : null;
    if (hr && (!local || hr.saved >= Number(local.saved)))
      local = { body: JSON.stringify(hr.data), saved: hr.saved };
    if (this.offline && local)
      return {
        ok: true,
        status: 200,
        data: JSON.parse(String(local.body)),
        source: "offline",
        cachedAt: Number(local.saved),
      };
    const result = await sender(request);
    if (result.ok) {
      this.offline = false;
      if (loggingIn || request.path === SESSION_PATH) {
        const parsed = sessionEnvelopeSchema.safeParse(result.data);
        if (parsed.success) {
          await this.remember(parsed.data);
          if (
            this.context()?.session.permissions.some((p) =>
              ["can_manage_suppliers", "hr.view", "hr.self"].includes(p),
            )
          ) {
            void this.synchronize().catch((error: unknown) => {
              this.error = error instanceof Error ? error.message : "تعذّرت المزامنة";
            });
          }
        }
      } else if (readable && context && context.id === this.context()?.id) {
        await this.store.write(() => {
          this.store.run("INSERT OR REPLACE INTO responses VALUES (?,?,?,?)", [
            context.id,
            cacheKey(request),
            JSON.stringify(result.data),
            this.now(),
          ]);
          this.store.run(
            "DELETE FROM responses WHERE rowid IN (SELECT rowid FROM responses WHERE scope=? ORDER BY saved DESC LIMIT -1 OFFSET 500)",
            [context.id],
          );
        });
      }
      return result;
    }
    if (result.failure === "unauthenticated" || result.failure === "password_change_required")
      await this.deactivate();
    if (result.failure === "http" && result.status === 403 && context) {
      await this.store.write(() =>
        this.store.run("DELETE FROM responses WHERE scope=? AND key=?", [context.id, cacheKey(request)]),
      );
      await this.deactivate();
    }
    if (!connectivity(result)) return result;
    this.offline = true;
    if (request.path === SESSION_PATH && context)
      return {
        ok: true,
        status: 200,
        data: { ok: true, session: context.session },
        source: "offline",
        cachedAt: context.verified,
      };
    if (request.path === SESSION_PATH && this.store.one("SELECT value FROM metadata WHERE key='active'"))
      return { ok: false, failure: "unauthenticated" };
    if (local && context?.id === this.context()?.id)
      return {
        ok: true,
        status: 200,
        data: JSON.parse(String(local.body)),
        source: "offline",
        cachedAt: Number(local.saved),
      };
    return result;
  }

  status(): OfflineStatus {
    const context = this.context();
    const rows = context
      ? this.store.all(
          "SELECT *, (SELECT receipt FROM operation_reservations WHERE operation_id=operations.id) AS local_receipt FROM operations WHERE scope=? ORDER BY (status IN ('done','cancelled')),created DESC,id DESC LIMIT 500",
          [context.id],
        )
      : [];
    const operations: OfflineOperation[] = rows.map((r) => ({
      id: String(r.id),
      label: String(r.label),
      total: Number(r.total),
      createdAt: Number(r.created),
      status: String(r.status) as OfflineOperation["status"],
      error: r.error === null ? null : String(r.error),
      invoiceNo: r.invoice === null ? null : String(r.invoice),
      ...(JSON.parse(String(r.payload)).kind === "pos" ? { kind: "pos" as const } : {}),
      ...(JSON.parse(String(r.payload)).kind === "finance" ? { kind: "finance" as const } : {}),
      ...(JSON.parse(String(r.payload)).kind === "hr"
        ? {
            kind: "hr" as const,
            invoiceNo: r.status === "done" ? `HR-${String(r.id).slice(0, 8)}` : null,
            canDiscard:
              r.status === "conflict" && hrOperationSchema.parse(JSON.parse(String(r.payload))).localAllowed,
          }
        : {}),
      ...(r.local_receipt ? { reserved: true, localInvoiceNo: String(r.local_receipt) } : {}),
    }));
    const counts = context
      ? this.store.all("SELECT status,COUNT(*) AS count FROM operations WHERE scope=? GROUP BY status", [
          context.id,
        ])
      : [];
    return {
      hr: this.hr.status(),
      snapshot: this.snapshot.status(),
      stock: this.stock.status(),
      available: !!context,
      lastVerifiedAt: context?.verified ?? null,
      lastCachedAt: context
        ? Math.max(
            Number(
              this.store.one("SELECT MAX(saved) AS saved FROM responses WHERE scope=?", [context.id])?.saved,
            ) || 0,
            this.snapshot.active()?.manifest.captured_at ?? 0,
          ) || null
        : null,
      pending: counts
        .filter((r) => r.status === "pending" || r.status === "syncing")
        .reduce((n, r) => n + Number(r.count), 0),
      conflicts: counts.filter((r) => r.status === "conflict").reduce((n, r) => n + Number(r.count), 0),
      syncing: !!this.syncing,
      error: this.error,
      operations,
    };
  }

  private posRows(
    scope: string,
    dataset: "pos-products" | "customers" | "payment-accounts",
    path: string,
  ): Array<Record<string, unknown>> {
    const initial = this.snapshot.rows(dataset) as Array<Record<string, unknown>>;
    const rows =
      dataset === "payment-accounts"
        ? ((initial[0]?.value as { accounts?: Array<Record<string, unknown>> } | undefined)?.accounts ?? [])
        : [...initial];
    for (const r of this.store.all(
      "SELECT key,body FROM responses WHERE scope=? AND key LIKE ? ORDER BY saved",
      [scope, `["${path}"%`],
    )) {
      if (dataset === "customers") {
        const query = (JSON.parse(String(r.key)) as [string, Array<[string, unknown]>])[1];
        const branch = query.find(([key]) => key === "branch_id")?.[1];
        if (branch !== undefined && Number(branch) !== this.context()?.session.branch?.id) continue;
      }
      const body = JSON.parse(String(r.body)) as {
        rows?: Array<Record<string, unknown>>;
        accounts?: Array<Record<string, unknown>>;
      };
      rows.push(...(Array.isArray(body) ? body : (body.rows ?? body.accounts ?? [])));
    }
    return rows;
  }

  async savePosSale(
    operationId: string,
    raw: PosSale,
  ): Promise<{ id: string; localInvoiceNo: string; total: number }> {
    const id = z.string().uuid().parse(operationId);
    const input = posSaleSchema.parse(raw);
    const context = this.context();
    if (!context?.session.branch || !context.session.permissions.includes("view_pos"))
      throw new Error("يلزم تسجيل دخول حديث بصلاحية نقطة البيع وفرع محدد.");
    if (!context.session.offline_pos_enabled)
      throw new Error("حدّث السيرفر وسجّل الدخول أونلاين لتفعيل البيع المحلي من نقطة البيع.");
    let localInvoiceNo = "";
    await this.store.write(() => {
      const current = this.context();
      if (current?.id !== context.id || !current.session.permissions.includes("view_pos"))
        throw new Error("تغيّرت جلسة البيع؛ لم تُحفظ الفاتورة.");
      const existing = this.store.one("SELECT payload,scope FROM operations WHERE id=?", [id]);
      if (existing) {
        if (existing.scope !== context.id || String(existing.payload) !== JSON.stringify(input))
          throw new Error("لا يمكن تغيير بيانات بيع محفوظ بنفس المعرّف.");
        localInvoiceNo = String(
          this.store.one("SELECT receipt FROM operation_reservations WHERE operation_id=?", [id])?.receipt ??
            "",
        );
        if (!localInvoiceNo) throw new Error("بيانات إيصال البيع المحفوظ ناقصة.");
        return;
      }
      if (input.payment !== "credit" && !current.session.permissions.includes("pay_orders"))
        throw new Error("ليست لديك صلاحية التحصيل.");
      if (
        Number(
          this.store.one(
            "SELECT COUNT(*) AS n FROM operations WHERE scope=? AND status NOT IN ('done','cancelled')",
            [context.id],
          )?.n,
        ) >= 500
      )
        throw new Error("أكمل مزامنة العمليات المحفوظة أولاً.");
      const customer = this.posRows(context.id, "customers", "/pos/search-customer")
        .reverse()
        .find((r) => r.id === input.customerId);
      if (!customer || customer.blacklisted || customer.name !== input.customerName)
        throw new Error("حمّل بيانات زبون صالح أونلاين قبل البيع المحلي.");
      const products = this.posRows(context.id, "pos-products", "/pos/api/products");
      for (const item of input.items) {
        const product = [...products].reverse().find((r) => r.id === item.product_id);
        if (!product) throw new Error("حمّل بيانات الأصناف أونلاين قبل البيع المحلي.");
        const colors = product.colors as Array<{ name: string; sale_price?: number }> | undefined;
        const color = colors?.find((c) => c.name === item.variant_color);
        if ((product.has_colors && !color) || (!product.has_colors && item.variant_color))
          throw new Error("اختر لوناً صحيحاً للصنف.");
        const price = color?.sale_price ?? product.price;
        if (!current.session.permissions.includes("edit_price") && item.price !== price)
          throw new Error("لا تملك صلاحية تعديل سعر الصنف.");
      }
      if (input.payment !== "credit") {
        const account = this.posRows(context.id, "payment-accounts", "/orders/payment-accounts")
          .reverse()
          .find((r) => r.id === input.accountId);
        if (
          !account ||
          account.branch_id !== current.session.branch?.id ||
          (String(account.type).toLowerCase() === "cash") !== (input.payment === "cash")
        )
          throw new Error("حمّل حساب تحصيل صالح لهذا الفرع أونلاين أولاً.");
      }
      localInvoiceNo = this.stock.consume(context.id, id, input);
      this.store.run("INSERT INTO operations VALUES (?,?,?,?,?,?, 'pending',NULL,NULL)", [
        id,
        context.id,
        JSON.stringify(input),
        `بيع · ${input.customerName}`,
        input.total,
        this.now(),
      ]);
    });
    return { id, localInvoiceNo, total: input.total };
  }

  async posReceipt(id: string): Promise<{
    number: string;
    sale: PosSale;
    names: string[];
    created: number;
    invoice: string | null;
    timeFormat?: "12" | "24";
  }> {
    await this.store.settled();
    const context = this.context();
    if (!context?.session.permissions.includes("print_pos_invoice"))
      throw new Error("غير مصرح بطباعة إيصال البيع.");
    const row = this.store.one("SELECT * FROM operations WHERE id=? AND scope=?", [
      z.string().uuid().parse(id),
      context.id,
    ]);
    if (!row) throw new Error("البيع غير موجود لهذا المستخدم والفرع.");
    const sale = posSaleSchema.parse(JSON.parse(String(row.payload)));
    const receipt = this.store.one("SELECT receipt FROM operation_reservations WHERE operation_id=?", [id]);
    if (!receipt) throw new Error("رقم الإيصال المحلي غير موجود.");
    return {
      number: String(receipt.receipt),
      timeFormat: context.session.display_time_format ?? "12",
      sale,
      created: Number(row.created),
      invoice: row.invoice ? String(row.invoice) : null,
      names: sale.items.map((i) =>
        String(
          this.store.one("SELECT name FROM device_stock WHERE scope=? AND product_id=? LIMIT 1", [
            context.id,
            i.product_id,
          ])?.name ?? `#${i.product_id}`,
        ),
      ),
    };
  }

  async saveSupplierDraft(raw: SupplierDraft): Promise<{ id: string; localInvoiceNo?: string }> {
    const input = supplierDraftSchema.parse(raw);
    const context = this.context();
    if (!context?.session.permissions.includes("can_manage_suppliers"))
      throw new Error("يلزم تسجيل دخول حديث بصلاحية الموردين لحفظ مسودة محلية.");
    const id = randomUUID();
    let localInvoiceNo: string | undefined;
    await this.store.write(() => {
      if (
        context.id !== this.context()?.id ||
        !this.context()?.session.permissions.includes("can_manage_suppliers")
      )
        throw new Error("تغيّرت جلسة المستخدم أو الصلاحيات؛ أعد فتح النموذج.");
      const count = Number(
        this.store.one(
          "SELECT COUNT(*) AS count FROM operations WHERE scope=? AND status NOT IN ('done','cancelled')",
          [context.id],
        )?.count ?? 0,
      );
      if (count >= 500) throw new Error("يوجد 500 عملية محلية غير مكتملة؛ زامن العمليات أولاً.");
      if (input.stockMode !== "reserved") {
        // Tentative local allocations stop one device queuing the same last piece twice.
        // They are not server quotas and cannot authorize delivery while offline.
        const held = this.store
          .all("SELECT payload FROM operations WHERE scope=? AND status IN ('pending','syncing')", [
            context.id,
          ])
          .flatMap((r) => {
            const payload = JSON.parse(String(r.payload)) as { kind?: string };
            if (payload.kind === "hr" || payload.kind === "finance") return [];
            return (
              payload.kind === "pos" ? posSaleSchema.parse(payload) : supplierDraftSchema.parse(payload)
            ).items;
          });
        const snapshots = this.store.all("SELECT body FROM responses WHERE scope=? ORDER BY saved DESC", [
          context.id,
        ]);
        const productSnapshots = snapshots.flatMap((r) => {
          const body: unknown = JSON.parse(String(r.body));
          return Array.isArray(body)
            ? (body as Array<{
                id?: number;
                quantity?: number;
                colors?: Array<{ name: string; qty: number }>;
              }>)
            : [];
        });
        productSnapshots.push(
          ...(this.snapshot.rows("supplier-products") as Array<{
            id: number;
            quantity?: number;
            colors?: Array<{ name: string; qty: number }>;
          }>),
        );
        for (const productId of new Set(input.items.map((i) => i.product_id))) {
          const product = productSnapshots.find((p) => p.id === productId && typeof p.quantity === "number");
          if (!product || typeof product.quantity !== "number")
            throw new Error("حمّل معلومات المنتج أونلاين قبل حفظ مسودة محلية.");
          const lines = [...held, ...input.items].filter((i) => i.product_id === productId);
          if (lines.reduce((n, i) => n + i.qty, 0) > product.quantity)
            throw new Error("الكمية المحفوظة في المسودات تتجاوز آخر مخزون محمّل لهذا الجهاز.");
          for (const color of product.colors ?? []) {
            if (
              lines.filter((i) => i.variant_color === color.name).reduce((n, i) => n + i.qty, 0) > color.qty
            )
              throw new Error(`الكمية المحفوظة من لون ${color.name} تتجاوز آخر مخزون محمّل.`);
          }
        }
      } else {
        localInvoiceNo = this.stock.consume(context.id, id, input);
      }
      this.store.run("INSERT INTO operations VALUES (?,?,?,?,?,?, 'pending',NULL,NULL)", [
        id,
        context.id,
        JSON.stringify(input),
        input.supplierName,
        input.items.reduce((n, i) => n + i.qty * i.price, 0),
        this.now(),
      ]);
    });
    return { id, ...(localInvoiceNo ? { localInvoiceNo } : {}) };
  }

  async retry(id: string): Promise<OfflineStatus> {
    const context = this.context();
    if (!context) throw new Error("سجّل الدخول إلى FINORA للمتابعة.");
    await this.store.write(() =>
      this.store.run(
        "UPDATE operations SET status='pending',error=NULL WHERE id=? AND scope=? AND status='conflict'",
        [id, context.id],
      ),
    );
    return this.synchronize();
  }

  async discardHR(id: string): Promise<OfflineStatus> {
    const context = this.context();
    if (!context) throw new Error("سجّل الدخول لمراجعة الطلبات المحلية");
    await this.store.write(() => {
      const row = this.store.one("SELECT payload,status FROM operations WHERE id=? AND scope=?", [
        id,
        context.id,
      ]);
      const parsed = row && hrOperationSchema.safeParse(JSON.parse(String(row.payload)));
      if (
        this.context()?.id !== context.id ||
        row?.status !== "conflict" ||
        !parsed?.success ||
        !parsed.data.localAllowed
      )
        throw new Error(
          "يمكن إلغاء طلب موارد بشرية غير مالي مرفوض فقط؛ الطلب غير المؤكد يحتاج التحقق من السيرفر",
        );
      this.store.run("UPDATE operations SET status='cancelled',error=? WHERE id=? AND scope=?", [
        "ألغى المستخدم الطلب المحلي المرفوض بعد المراجعة",
        id,
        context.id,
      ]);
    });
    return this.status();
  }

  synchronize(): Promise<OfflineStatus> {
    if (this.syncing) return this.syncing;
    this.syncing = this.flush().finally(() => {
      this.syncing = null;
    });
    return this.syncing;
  }

  async downloadSnapshot(restart = false): Promise<OfflineStatus> {
    const verified = await this.request({ method: "GET", path: SESSION_PATH });
    if (!verified.ok || verified.source === "offline")
      throw new Error("يلزم اتصال بالسيرفر لتنزيل نسخة البيانات.");
    await this.synchronize();
    if (restart) await this.snapshot.reset();
    await this.snapshot.download();
    await this.hr.download();
    return this.status();
  }

  async manageStock(kind: "reserve" | "return" | "resume", input?: ReserveStock): Promise<OfflineStatus> {
    const verified = await this.request({ method: "GET", path: SESSION_PATH });
    if (!verified.ok || verified.source === "offline")
      throw new Error("يلزم اتصال بالسيرفر لإدارة حصة الجهاز.");
    await this.synchronize();
    const context = this.context();
    if (
      kind !== "resume" &&
      context &&
      this.store.one("SELECT value FROM metadata WHERE key=?", [`restored-stock:${context.id}`])
    )
      throw Error("أكمل مراجعة حصة المخزون المستعادة من المزامنة أولاً");
    await this.stock.request(kind, input);
    await this.reconcileRestoredQuota();
    return this.status();
  }

  private async flush(): Promise<OfflineStatus> {
    // Background synchronization must not observe a draft whose checkpoint is still pending.
    await this.store.settled();
    const original = this.context();
    if (!original) return this.status();
    const pending = this.store.all(
      "SELECT * FROM operations WHERE scope=? AND status IN ('pending','syncing') ORDER BY created,rowid LIMIT 100",
      [original.id],
    );
    if (!pending.length) return this.status();
    const verified = await this.sender({ method: "GET", path: SESSION_PATH, timeoutMs: 10_000 });
    if (!verified.ok) {
      if (
        verified.failure === "unauthenticated" ||
        verified.failure === "password_change_required" ||
        (verified.failure === "http" && verified.status === 403)
      )
        await this.deactivate();
      this.error = "توقفت المزامنة؛ يلزم اتصال وجلسة FINORA فعّالة.";
      return this.status();
    }
    const session = sessionEnvelopeSchema.parse(verified.data);
    if (identity(this.server, session) !== original.id || this.context()?.id !== original.id) {
      this.error = "تغيّر المستخدم أو الفرع؛ لم تُرسل العمليات.";
      return this.status();
    }
    await this.remember(session);
    this.offline = false;
    this.error = null;
    const device = String(this.store.one("SELECT value FROM metadata WHERE key='device'")?.value);
    for (const selected of pending) {
      if (this.context()?.id !== original.id) break;
      // A foreground request can finish or change while session verification awaits.
      // Claim the current row atomically instead of reviving the captured batch row.
      const operation = await this.store.write(() => {
        if (this.context()?.id !== original.id) return null;
        const current = this.store.one("SELECT * FROM operations WHERE id=? AND scope=?", [
          String(selected.id),
          original.id,
        ]);
        if (!current || !["pending", "syncing"].includes(String(current.status))) return null;
        this.store.run("UPDATE operations SET status='syncing' WHERE id=?", [String(current.id)]);
        return current;
      });
      if (!operation) continue;
      const raw = JSON.parse(String(operation.payload)) as { kind?: string };
      if (raw.kind === "finance") {
        const stored = z.object({ kind: z.literal("finance"), request: finoraRequestSchema }).parse(raw);
        const allowed =
          session.permissions.includes("finance.view") && session.permissions.includes("finance.create");
        const response: FinoraResponse = allowed
          ? await this.sender(stored.request)
          : { ok: false, failure: "refused", detail: "تغيّرت صلاحية إنشاء السندات؛ راجع المسودة المحلية" };
        if (this.context()?.id !== original.id) break;
        const parsed = response.ok
          ? z
              .object({
                success: z.literal(true),
                data: z.object({ id: z.number().positive(), number: z.string(), status: z.literal("draft") }),
              })
              .safeParse(response.data)
          : null;
        const done = !!parsed?.success;
        const retry =
          connectivity(response) || (!response.ok && response.failure === "http" && response.status >= 500);
        await this.store.write(() =>
          this.store.run("UPDATE operations SET status=?,error=?,invoice=? WHERE id=?", [
            done ? "done" : retry ? "pending" : "conflict",
            done
              ? null
              : response.ok
                ? "الخادم لم يؤكد حفظ المسودة"
                : "detail" in response
                  ? response.detail || "راجع العملية"
                  : "تعذر الاتصال",
            parsed?.success ? parsed.data.data.number : null,
            String(operation.id),
          ]),
        );
        if (retry) break;
        continue;
      }
      if (raw.kind === "hr") {
        const stored = hrOperationSchema.parse(raw);
        if (stored.command.action === "attendance.record" && stored.command.payload.check_in_command_id) {
          const reference = this.store.one("SELECT status FROM operations WHERE id=? AND scope=?", [
            String(stored.command.payload.check_in_command_id),
            original.id,
          ]);
          if (reference?.status === "conflict" || reference?.status === "cancelled") {
            await this.store.write(() =>
              this.store.run("UPDATE operations SET status='conflict',error=? WHERE id=?", [
                "طلب الحضور المرتبط يحتاج مراجعة قبل اعتماد الانصراف",
                String(operation.id),
              ]),
            );
            continue;
          }
          if (reference && reference.status !== "done") continue;
        }
        const transmit = await this.store.write(() => {
          const current = this.store.one("SELECT status FROM operations WHERE id=? AND scope=?", [
            String(operation.id),
            original.id,
          ]);
          if (current?.status !== "syncing") return false;
          this.store.run("UPDATE operations SET payload=? WHERE id=?", [
            JSON.stringify({ ...stored, transmitted: true }),
            String(operation.id),
          ]);
          return true;
        });
        if (!transmit) continue;
        const response = await this.sender(
          finoraRequestSchema.parse({
            method: "POST",
            path: "/hr/api/commands",
            body: stored.command,
            timeoutMs: 30000,
          }),
        );
        if (this.context()?.id !== original.id) break;
        await this.finishHR(String(operation.id), original.id, response);
        if (
          response.ok &&
          this.store.one("SELECT status FROM operations WHERE id=?", [String(operation.id)])?.status !==
            "done"
        )
          break;
        if (
          connectivity(response) ||
          (!response.ok &&
            (response.failure === "invalid_response" ||
              (response.failure === "http" && (response.status >= 500 || response.status === 429))))
        )
          break;
        if (
          !response.ok &&
          (["unauthenticated", "password_change_required"].includes(response.failure) ||
            (response.failure === "http" && [401, 403].includes(response.status)))
        ) {
          await this.deactivate();
          break;
        }
        continue;
      }
      const posSale = raw.kind === "pos" ? posSaleSchema.parse(raw) : null;
      const draft = posSale ? null : supplierDraftSchema.parse(raw);
      if (posSale && !session.offline_pos_enabled) {
        this.error = "السيرفر لا يدعم مزامنة نقطة البيع المحلية؛ حدّثه ثم أعد المزامنة.";
        await this.store.write(() =>
          this.store.run("UPDATE operations SET status='pending',error=? WHERE id=?", [
            this.error,
            String(operation.id),
          ]),
        );
        break;
      }
      const reservation = this.store.one(
        "SELECT parts,receipt FROM operation_reservations WHERE operation_id=?",
        [String(operation.id)],
      );
      if ((posSale || draft?.stockMode === "reserved") && !reservation) {
        await this.store.write(() =>
          this.store.run("UPDATE operations SET status='conflict',error=? WHERE id=?", [
            "بيانات حصة البيع المحلي ناقصة؛ راجع العملية قبل إعادة المزامنة.",
            String(operation.id),
          ]),
        );
        this.error = "توقفت مزامنة بيع محلي لأن بيانات الحصة ناقصة.";
        continue;
      }
      const response = await this.sender({
        method: "POST",
        path: posSale ? "/api/v1/desktop/sync/pos-sale" : "/api/v1/desktop/sync/supplier-sale",
        timeoutMs: 30_000,
        body: {
          device_id: device,
          operation_id: String(operation.id),
          branch_id: original.session.branch?.id ?? null,
          ...(posSale
            ? {
                sale: posSale,
                created_at: Number(operation.created),
                local_invoice_no: String(reservation?.receipt),
              }
            : { supplier_id: draft?.supplierId ?? 0, items: draft?.items ?? [], note: draft?.note ?? "" }),
          ...(reservation
            ? { reservations: stockPartsSchema.parse(JSON.parse(String(reservation.parts))) }
            : {}),
        },
      });
      if (this.context()?.id !== original.id) break;
      if (response.ok) {
        const data = response.data as { success?: boolean; invoice_no?: string };
        if (data?.success !== true || typeof data.invoice_no !== "string") {
          this.error = "رد المزامنة غير صالح؛ ستُراجع العملية بنفس المعرّف.";
          break;
        }
        await this.store.write(() => {
          this.store.run("UPDATE operations SET status='done',error=NULL,invoice=? WHERE id=?", [
            data.invoice_no ?? null,
            String(operation.id),
          ]);
          this.store.run("DELETE FROM responses WHERE scope=?", [original.id]);
          this.store.run("UPDATE snapshots SET stale=1 WHERE scope=?", [original.id]);
        });
      } else if (
        connectivity(response) ||
        response.failure === "invalid_response" ||
        (response.failure === "http" && (response.status >= 500 || response.status === 429))
      ) {
        await this.store.write(() =>
          this.store.run("UPDATE operations SET status='pending' WHERE id=?", [String(operation.id)]),
        );
        this.error = "تعذّر الاتصال؛ العملية محفوظة وستُرسل بنفس المعرّف عند عودة الاتصال.";
        break;
      } else {
        const body = response.failure === "http" ? (response.data as { error?: string }) : null;
        const error =
          typeof body?.error === "string" ? body.error : "تحتاج العملية إلى مراجعة الصلاحيات أو البيانات.";
        await this.store.write(() =>
          this.store.run("UPDATE operations SET status='conflict',error=? WHERE id=?", [
            error,
            String(operation.id),
          ]),
        );
        if (response.failure === "unauthenticated" || response.failure === "password_change_required") {
          await this.deactivate();
          break;
        }
      }
    }
    return this.status();
  }

  private async finishHR(id: string, scope: string, response: FinoraResponse): Promise<void> {
    if (response.ok) {
      const receipt = response.data as { success?: boolean; id?: number };
      if (receipt?.success !== true || !Number.isSafeInteger(receipt.id) || (receipt.id ?? 0) <= 0) {
        await this.store.write(() =>
          this.store.run(
            "UPDATE operations SET status='pending',error=? WHERE id=? AND scope=? AND status NOT IN ('done','cancelled')",
            ["تعذّر التحقق من تأكيد السيرفر؛ سيُراجع بنفس المعرّف", id, scope],
          ),
        );
        return;
      }
      await this.store.write(() => {
        const stored = this.store.one("SELECT payload,status FROM operations WHERE id=? AND scope=?", [
          id,
          scope,
        ]);
        if (!stored || ["done", "cancelled"].includes(String(stored.status))) return;
        if (stored)
          this.store.run("UPDATE operations SET payload=? WHERE id=?", [
            JSON.stringify({
              ...hrOperationSchema.parse(JSON.parse(String(stored.payload))),
              acknowledgedAt: this.now(),
            }),
            id,
          ]);
        this.store.run("UPDATE operations SET status='done',error=NULL,invoice=? WHERE id=?", [
          JSON.stringify(receipt),
          id,
        ]);
        this.store.run("DELETE FROM responses WHERE scope=? AND key LIKE ?", [scope, '["/hr/api/%']);
        this.store.run("UPDATE hr_snapshots SET stale=1 WHERE scope=?", [scope]);
      });
      return;
    }
    const uncertain =
      connectivity(response) ||
      response.failure === "invalid_response" ||
      (response.failure === "http" && (response.status >= 500 || response.status === 429));
    const body = response.failure === "http" ? (response.data as { error?: string }) : null;
    const error =
      typeof body?.error === "string"
        ? body.error
        : uncertain
          ? "الطلب محفوظ بانتظار تأكيد السيرفر"
          : "راجع الصلاحيات أو بيانات الطلب";
    await this.store.write(() =>
      this.store.run(
        "UPDATE operations SET status=?,error=? WHERE id=? AND scope=? AND status NOT IN ('done','cancelled')",
        [uncertain ? "pending" : "conflict", error, id, scope],
      ),
    );
  }

  private async financeCommand(request: FinoraRequest, sender: Sender): Promise<FinoraResponse> {
    const context = this.context();
    if (!context)
      return { ok: false, failure: "unauthenticated", detail: "حدّث جلسة الدخول قبل حفظ العملية" };
    const body = z
      .object({ operation: z.string(), idempotency_key: z.string().min(12).max(80) })
      .passthrough()
      .safeParse(request.body);
    if (!body.success) return { ok: false, failure: "refused", detail: "بيانات السند غير صحيحة" };
    if (!this.offline) {
      const response = await sender(request);
      if (!connectivity(response)) return response;
      this.offline = true;
    }
    if (body.data.operation !== "voucher.create" || (body.data.intent ?? "draft") !== "draft")
      return { ok: false, failure: "network", detail: "الاعتماد وتحريك الأرصدة يحتاجان اتصالاً بالخادم" };
    if (
      !context.session.permissions.includes("finance.view") ||
      !context.session.permissions.includes("finance.create")
    )
      return { ok: false, failure: "refused", detail: "يلزم صلاحية إنشاء السندات" };
    const amount = Number(body.data.amount);
    if (!Number.isSafeInteger(amount) || amount <= 0 || JSON.stringify(request).length > 64000)
      return { ok: false, failure: "refused", detail: "تحقق من مبلغ وحجم المسودة" };
    const cached = this.store.one("SELECT body FROM responses WHERE scope=? AND key=?", [
      context.id,
      cacheKey({ method: "GET", path: "/api/finance/meta" }),
    ]);
    const metadata = z
      .object({
        success: z.literal(true),
        data: z.object({
          categories: z.array(
            z.object({ id: z.string(), kind: z.string(), label: z.string(), party_type: z.string() }),
          ),
          accounts: z.array(z.object({ id: z.number(), name: z.string(), branch_id: z.number().nullable() })),
        }),
      })
      .safeParse(cached ? JSON.parse(String(cached.body)) : null);
    if (!metadata.success)
      return { ok: false, failure: "refused", detail: "افتح الحسابات أثناء الاتصال قبل حفظ مسودة محلية" };
    const category = metadata.data.data.categories.find((c) => c.id === body.data.category),
      account = metadata.data.data.accounts.find((a) => a.id === Number(body.data.treasury_account_id));
    if (!category || !account || account.branch_id !== Number(body.data.branch_id))
      return { ok: false, failure: "refused", detail: "الحساب أو سبب العملية غير موجود في الفرع المحفوظ" };
    const key = body.data.idempotency_key;
    await this.store.write(() => {
      if (this.context()?.id !== context.id) throw Error("تغيّرت جلسة الدخول");
      const previous = this.store.one("SELECT payload,scope FROM operations WHERE id=?", [key]);
      const payload = JSON.stringify({ kind: "finance", request });
      if (previous && (previous.scope !== context.id || previous.payload !== payload))
        throw Error("معرف العملية مستخدم لمسودة مختلفة");
      if (!previous)
        this.store.run("INSERT INTO operations VALUES (?,?,?,?,?,?, 'pending',NULL,NULL)", [
          key,
          context.id,
          payload,
          `${category.label} — مسودة محلية`,
          amount,
          this.now(),
        ]);
    });
    return {
      ok: true,
      status: 200,
      source: "offline",
      data: {
        success: true,
        data: {
          id: -Math.max(1, parseInt(createHash("sha256").update(key).digest("hex").slice(0, 7), 16)),
          number: `LOCAL-${key.slice(0, 8)}`,
          kind: category.kind,
          category: category.id,
          category_label: category.label,
          party_type: category.party_type,
          party_id: body.data.party_id ? Number(body.data.party_id) : null,
          party_name: String(body.data.party_name || ""),
          amount,
          account_name: account.name,
          treasury_account_id: account.id,
          target_account_id: body.data.target_account_id ? Number(body.data.target_account_id) : null,
          branch_id: account.branch_id,
          transaction_date: String(
            body.data.transaction_date || new Date(this.now()).toISOString().slice(0, 10),
          ),
          status: "local_pending",
          version: 0,
          notes: String(body.data.notes || ""),
          source_type: null,
          source_id: null,
          reversal_id: null,
        },
      },
    };
  }

  private async hrCommand(request: FinoraRequest, sender: Sender): Promise<FinoraResponse> {
    const parsed = hrCommandSchema.safeParse(request.body),
      context = this.context();
    if (!parsed.success)
      return { ok: false, failure: "refused", detail: "بيانات أمر الموارد البشرية غير صحيحة" };
    if (!context)
      return { ok: false, failure: "unauthenticated", detail: "حدّث جلسة الدخول قبل حفظ العملية" };
    if (!context.session.permissions.some((p) => ["hr.view", "hr.self"].includes(p)))
      return { ok: false, failure: "refused", detail: "يلزم صلاحية الموارد البشرية" };
    let command = parsed.data;
    const localAllowed = offlineHRAllowed(command, context.session.permissions);
    if (this.offline && !localAllowed)
      return { ok: false, failure: "network", detail: "هذه العملية تحتاج تأكيداً مركزياً" };
    if (JSON.stringify(command).length > 6 * 1024 * 1024)
      return { ok: false, failure: "refused", detail: "حجم الطلب أكبر من الحد المسموح" };
    await this.store.write(() => {
      if (this.context()?.id !== context.id) throw new Error("تغيّرت جلسة الدخول قبل حفظ العملية");
      const pendingHR = this.store.all(
        "SELECT id,payload FROM operations WHERE scope=? AND status IN ('pending','syncing') ORDER BY created,rowid",
        [context.id],
      );
      if (this.offline && command.action === "employee.update") {
        const previous = pendingHR
          .map((row) => hrOperationSchema.safeParse(JSON.parse(String(row.payload))))
          .find(
            (p) =>
              p.success &&
              p.data.command.action === command.action &&
              p.data.command.payload.person_id === command.payload.person_id,
          );
        if (previous?.success) {
          if (previous.data.transmitted !== false)
            throw new Error("التعديل السابق بانتظار تأكيد السيرفر؛ زامنه قبل تغيير البيانات مرة أخرى");
          if (previous.data.command.payload.version !== command.payload.version)
            throw new Error("تغيرت نسخة الموظف؛ زامن التعديل السابق وراجعه قبل إضافة تعديل جديد");
          command = {
            ...previous.data.command,
            payload: { ...previous.data.command.payload, ...command.payload },
          };
          this.store.run("UPDATE operations SET payload=? WHERE id=?", [
            JSON.stringify({ ...previous.data, command, modifiedAt: this.now() }),
            command.id,
          ]);
        }
      }
      if (command.action === "attendance.record") {
        const latestEvent = pendingHR
          .map((row) => hrOperationSchema.safeParse(JSON.parse(String(row.payload))))
          .reverse()
          .find(
            (p) =>
              p.success &&
              p.data.command.action === command.action &&
              p.data.command.payload.person_id === command.payload.person_id,
          );
        const baghdadDay = (at: unknown) =>
          typeof at === "string" && Number.isFinite(Date.parse(at))
            ? new Date(Date.parse(at) + 3 * 3600000).toISOString().slice(0, 10)
            : null;
        const sameEvent = pendingHR
          .map((row) => hrOperationSchema.safeParse(JSON.parse(String(row.payload))))
          .find(
            (p) =>
              p.success &&
              p.data.command.action === command.action &&
              p.data.command.payload.person_id === command.payload.person_id &&
              p.data.command.payload.event === command.payload.event &&
              (p.data.command.payload.occurred_at === command.payload.occurred_at ||
                (latestEvent?.success &&
                  latestEvent.data.command.id === p.data.command.id &&
                  baghdadDay(p.data.command.payload.occurred_at) ===
                    baghdadDay(command.payload.occurred_at))),
          );
        if (sameEvent?.success) command = sameEvent.data.command;
        else if (command.payload.event === "check_out") {
          const first = pendingHR
            .map((row) => hrOperationSchema.safeParse(JSON.parse(String(row.payload))))
            .reverse()
            .find(
              (p) =>
                p.success &&
                p.data.command.action === "attendance.record" &&
                p.data.command.payload.person_id === command.payload.person_id &&
                p.data.command.payload.event === "check_in",
            );
          if (first?.success)
            command = {
              ...command,
              payload: { ...command.payload, check_in_command_id: first.data.command.id },
            };
          else if (this.offline && !command.payload.attendance_id) {
            const detail = this.hr.query({
              method: "GET",
              path: `/hr/api/people/${Number(command.payload.person_id)}`,
            })?.data as { attendance?: { id?: number | null } } | undefined;
            if (detail?.attendance?.id && detail.attendance.id > 0)
              command = { ...command, payload: { ...command.payload, attendance_id: detail.attendance.id } };
          }
        }
        if (
          this.offline &&
          !sameEvent?.success &&
          command.payload.event === "check_in" &&
          typeof command.payload.occurred_at === "string"
        ) {
          const date = new Date(Date.parse(command.payload.occurred_at) + 3 * 3600000).toISOString(),
            day = date.slice(0, 10),
            previousDay = new Date(Date.parse(day + "T12:00:00Z") - 86400000).toISOString().slice(0, 10);
          const at = (on: string) => {
            const result = this.hr.query({
              method: "GET",
              path: "/hr/api/workspace",
              query: { tab: "attendance", date: on, person_id: Number(command.payload.person_id) },
            })?.data as { rows?: Record<string, unknown>[] } | undefined;
            return result?.rows?.find((r) => r.person_id === command.payload.person_id);
          };
          const previous = at(previousDay),
            current = at(day),
            previousShift = previous?.shift as Record<string, unknown> | null | undefined;
          const cached =
            previousShift &&
            typeof previousShift.starts === "string" &&
            typeof previousShift.ends === "string" &&
            previousShift.ends <= previousShift.starts &&
            date.slice(11, 16) <= previousShift.ends
              ? previous
              : current;
          if (cached?.check_in)
            throw new Error("الحضور مسجل محلياً لهذا اليوم؛ سجّل الانصراف أو راجع الطلب المحفوظ");
          if (cached) {
            const shift = cached.shift as Record<string, unknown> | null;
            command = {
              ...command,
              payload: {
                ...command.payload,
                shift_id: shift?.id ?? null,
                shift_version: shift?.version ?? 0,
              },
            };
          }
        }
      }
      const signature = JSON.stringify([command.action, command.payload]);
      const paymentTarget = (
        {
          "payroll.pay": "item_id",
          "advance.pay": "advance_id",
          "commission.pay": "commission_id",
        } as Record<string, string>
      )[command.action];
      if (paymentTarget) {
        const unresolved = this.store
          .all("SELECT payload FROM operations WHERE scope=? AND status IN ('pending','syncing')", [
            context.id,
          ])
          .some((row) => {
            const pending = hrOperationSchema.safeParse(JSON.parse(String(row.payload)));
            return (
              pending.success &&
              pending.data.command.action === command.action &&
              pending.data.command.payload[paymentTarget] === command.payload[paymentTarget] &&
              JSON.stringify([pending.data.command.action, pending.data.command.payload]) !== signature
            );
          });
        if (unresolved)
          throw new Error("توجد دفعة لهذا الاستحقاق بانتظار التأكيد؛ زامنها أولاً قبل إنشاء دفعة مختلفة");
      }
      const duplicate = this.store
        .all("SELECT id,payload FROM operations WHERE scope=? AND status IN ('pending','syncing')", [
          context.id,
        ])
        .find((row) => {
          const payload = hrOperationSchema.safeParse(JSON.parse(String(row.payload)));
          return (
            payload.success &&
            JSON.stringify([payload.data.command.action, payload.data.command.payload]) === signature
          );
        });
      if (duplicate) command = hrOperationSchema.parse(JSON.parse(String(duplicate.payload))).command;
      let existing = this.store.one("SELECT scope,payload,status FROM operations WHERE id=?", [command.id]);
      if (
        existing?.scope === context.id &&
        existing.status === "conflict" &&
        JSON.stringify(hrOperationSchema.parse(JSON.parse(String(existing.payload))).command) !==
          JSON.stringify(command)
      ) {
        command = { ...command, id: randomUUID() };
        existing = undefined;
      }
      if (
        existing &&
        (existing.scope !== context.id ||
          JSON.stringify(hrOperationSchema.parse(JSON.parse(String(existing.payload))).command) !==
            JSON.stringify(command))
      )
        throw new Error("معرّف العملية مستخدم لطلب مختلف");
      if (!existing)
        this.store.run("INSERT INTO operations VALUES (?,?,?,?,?,?, 'pending',NULL,NULL)", [
          command.id,
          context.id,
          JSON.stringify({ kind: "hr", command, localAllowed, transmitted: false, modifiedAt: this.now() }),
          `${HR_ACTION_LABELS[command.action] ?? "عملية موارد بشرية"}${command.payload.person_id ? ` #${String(command.payload.person_id)}` : ""}`,
          0,
          this.now(),
        ]);
    });
    const old = this.store.one("SELECT status,invoice FROM operations WHERE id=?", [command.id]);
    if (old?.status === "done" && old.invoice)
      return { ok: true, status: 200, data: JSON.parse(String(old.invoice)) };
    if (this.offline)
      return { ok: true, status: 202, data: { success: true, id: 0, pending: true }, source: "offline" };
    await this.store.write(() => {
      const stored = this.store.one("SELECT payload FROM operations WHERE id=?", [command.id]);
      if (stored)
        this.store.run("UPDATE operations SET payload=? WHERE id=?", [
          JSON.stringify({
            ...hrOperationSchema.parse(JSON.parse(String(stored.payload))),
            transmitted: true,
          }),
          command.id,
        ]);
    });
    const response = await sender(finoraRequestSchema.parse({ ...request, body: command }));
    if (this.context()?.id !== context.id)
      return { ok: false, failure: "unauthenticated", detail: "تغيّرت جلسة الدخول" };
    await this.finishHR(command.id, context.id, response);
    if (
      response.ok &&
      this.store.one("SELECT status FROM operations WHERE id=?", [command.id])?.status !== "done"
    )
      return {
        ok: false,
        failure: "invalid_response",
        detail: "تعذّر تأكيد العملية؛ الطلب محفوظ وسيُراجع بنفس المعرّف",
      };
    if (
      !response.ok &&
      (["unauthenticated", "password_change_required"].includes(response.failure) ||
        (response.failure === "http" && [401, 403].includes(response.status)))
    )
      await this.deactivate();
    if (connectivity(response)) {
      this.offline = true;
      if (localAllowed)
        return { ok: true, status: 202, data: { success: true, id: 0, pending: true }, source: "offline" };
    }
    return response;
  }
}
