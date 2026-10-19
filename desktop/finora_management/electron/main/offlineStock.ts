import { randomUUID } from "node:crypto";
import { z } from "zod";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
import {
  reserveStockSchema,
  stockGrantSchema,
  stockPartsSchema,
  type ReserveStock,
  type DeviceStockStatus,
} from "../../shared/stock";
import type { SupplierDraft } from "../../shared/offline";
import type { FinoraSession } from "../../src/api/finora/schemas";
import { OfflineDatabase } from "./offlineDatabase";

type Context = { id: string; session: FinoraSession };
export class OfflineStock {
  private running = false;
  constructor(
    private store: OfflineDatabase,
    private context: () => Context | null,
    private sender: (request: FinoraRequest) => Promise<FinoraResponse>,
  ) {}
  async returnRecovered(parts: { id: string; qty: number }[]) {
    const context = this.context();
    if (!context?.session.branch) throw Error("حدّث جلسة الدخول قبل مراجعة الرصيد المستعاد");
    const id = randomUUID();
    const payload = {
      id,
      device_id: String(this.store.one("SELECT value FROM metadata WHERE key='device'")?.value),
      branch_id: context.session.branch.id,
      parts: stockPartsSchema.parse(parts),
    };
    await this.store.write(() => {
      this.assertScope(context);
      if (this.store.one("SELECT id FROM stock_requests WHERE scope=? AND state='pending'", [context.id]))
        throw Error("أكمل طلب الحصة الحالي أولاً");
      this.store.run("INSERT INTO stock_requests VALUES (?,?,?,?,'pending',NULL)", [
        id,
        context.id,
        "return",
        JSON.stringify(payload),
      ]);
    });
    await this.request("resume");
  }
  status(): DeviceStockStatus {
    const context = this.context();
    const task =
      context &&
      this.store.one("SELECT * FROM stock_requests WHERE scope=? AND state='pending'", [context.id]);
    const last =
      context &&
      this.store.one("SELECT error FROM stock_requests WHERE scope=? ORDER BY rowid DESC LIMIT 1", [
        context.id,
      ]);
    return {
      rows: context
        ? this.store
            .all("SELECT * FROM device_stock WHERE scope=? ORDER BY rowid", [context.id])
            .map((r) => ({
              id: String(r.id),
              productId: Number(r.product_id),
              name: String(r.name),
              color: String(r.color),
              quantity: Number(r.quantity),
              used: Number(r.used),
              returned: Number(r.returned),
              frozen: !!r.frozen,
              available: r.frozen ? 0 : Number(r.quantity) - Number(r.used) - Number(r.returned),
            }))
        : [],
      pendingRequest: !!task,
      busy: this.running,
      error: task?.error ? String(task.error) : last?.error ? String(last.error) : null,
    };
  }
  private assertScope(context: Context) {
    if (
      this.context()?.id !== context.id ||
      !this.context()?.session.permissions.some((p) => ["can_manage_suppliers", "view_pos"].includes(p))
    )
      throw new Error("تغيّرت الجلسة أو الصلاحيات؛ توقفت إدارة حصة الجهاز.");
  }
  async request(kind: "reserve" | "return" | "resume", raw?: ReserveStock): Promise<void> {
    if (this.running) throw new Error("يوجد طلب حصة جارٍ؛ انتظر اكتماله.");
    this.running = true;
    try {
      await this.perform(kind, raw);
    } finally {
      this.running = false;
    }
  }
  private async perform(kind: "reserve" | "return" | "resume", raw?: ReserveStock) {
    await this.store.settled();
    const context = this.context();
    if (
      !context?.session.branch ||
      !context.session.permissions.some((p) => ["can_manage_suppliers", "view_pos"].includes(p))
    )
      throw new Error("سجّل الدخول أونلاين بصلاحية البيع قبل إدارة الحصة.");
    let task = this.store.one("SELECT * FROM stock_requests WHERE scope=? AND state='pending'", [context.id]);
    if (task && kind !== "resume") throw new Error("أكمل طلب الحصة السابق من إعدادات الأوفلاين أولاً.");
    if (!task) {
      if (kind === "resume") throw new Error("لا يوجد طلب حصة معلّق.");
      const id = randomUUID();
      const device = String(this.store.one("SELECT value FROM metadata WHERE key='device'")?.value);
      await this.store.write(() => {
        this.assertScope(context);
        const items = kind === "reserve" ? reserveStockSchema.parse(raw) : undefined;
        const parts =
          kind === "return"
            ? this.store
                .all(
                  "SELECT id,quantity-used-returned AS remaining FROM device_stock WHERE scope=? AND frozen=0 AND quantity>used+returned",
                  [context.id],
                )
                .map((r) => ({ id: String(r.id), qty: Number(r.remaining) }))
            : undefined;
        if (parts && !parts.length) throw new Error("لا توجد كمية غير مستخدمة لإعادتها.");
        const payload = {
          id,
          device_id: device,
          branch_id: context.session.branch?.id,
          ...(items ? { items } : { parts: stockPartsSchema.parse(parts) }),
        };
        // Freeze before contacting the server: an uncertain return can never be sold again locally.
        for (const part of parts ?? [])
          this.store.run("UPDATE device_stock SET frozen=1 WHERE id=? AND scope=?", [part.id, context.id]);
        this.store.run("INSERT INTO stock_requests VALUES (?,?,?,?,'pending',NULL)", [
          id,
          context.id,
          kind,
          JSON.stringify(payload),
        ]);
      });
      task = this.store.one("SELECT * FROM stock_requests WHERE id=?", [id]);
    }
    if (!task) throw new Error("تعذّر حفظ طلب حصة الجهاز.");
    const payload = JSON.parse(String(task.payload)) as {
      id: string;
      device_id: string;
      branch_id: number;
      items?: ReserveStock;
      parts?: Array<{ id: string; qty: number }>;
    };
    const taskId = String(task.id);
    try {
      const response = await this.sender({
        method: "POST",
        path: `/api/v1/desktop/stock/${String(task.kind)}`,
        body: payload,
        timeoutMs: 30_000,
      });
      this.assertScope(context);
      if (!response.ok) {
        const body = response.failure === "http" ? (response.data as { error?: unknown }) : null;
        if (task.kind === "reserve" && response.failure === "http" && [400, 409].includes(response.status))
          await this.store.write(() =>
            this.store.run("UPDATE stock_requests SET state='failed' WHERE id=?", [taskId]),
          );
        throw new Error(
          typeof body?.error === "string"
            ? body.error
            : "تعذّر الاتصال؛ طلب الحصة محفوظ. استأنفه بنفس المعرّف من الإعدادات.",
        );
      }
      const grant = task.kind === "reserve" ? stockGrantSchema.parse(response.data) : null;
      if (grant) {
        if (
          grant.id !== taskId ||
          grant.device_id !== payload.device_id ||
          grant.employee_id !== context.session.user.id ||
          grant.branch_id !== payload.branch_id
        )
          throw new Error("الحصة المستلمة لا تطابق الجهاز أو المستخدم أو الفرع.");
        const expected = new Map(
          (payload.items ?? []).map((i) => [`${i.product_id}:${i.variant_color?.trim() ?? ""}`, i.qty]),
        );
        const actual = new Map(
          grant.allocations.map((i) => [`${i.product_id}:${i.variant_color}`, i.quantity]),
        );
        if (
          expected.size !== (payload.items?.length ?? 0) ||
          actual.size !== grant.allocations.length ||
          actual.size !== expected.size ||
          [...actual].some(([key, qty]) => expected.get(key) !== qty)
        )
          throw new Error("أصناف أو كميات الحصة المستلمة غير مطابقة لطلب الحجز.");
      } else {
        const returned = z.object({ success: z.literal(true), id: z.string().uuid() }).parse(response.data);
        if (returned.id !== taskId) throw new Error("معرّف إعادة الحصة غير مطابق.");
      }
      await this.store.write(() => {
        this.assertScope(context);
        if (grant)
          for (const item of grant.allocations)
            this.store.run(
              "INSERT OR IGNORE INTO device_stock(id,scope,grant_id,product_id,name,color,quantity) VALUES (?,?,?,?,?,?,?)",
              [item.id, context.id, grant.id, item.product_id, item.name, item.variant_color, item.quantity],
            );
        else
          for (const part of payload.parts ?? [])
            this.store.run(
              "UPDATE device_stock SET returned=returned+?,frozen=0 WHERE id=? AND scope=? AND frozen=1",
              [part.qty, part.id, context.id],
            );
        this.store.run("UPDATE stock_requests SET state='done',error=NULL WHERE id=?", [taskId]);
      });
    } catch (error) {
      await this.store.write(() =>
        this.store.run("UPDATE stock_requests SET error=? WHERE id=?", [
          error instanceof Error ? error.message : "تعذّرت إدارة الحصة",
          taskId,
        ]),
      );
      throw error;
    }
  }

  /** Inside the caller's durable transaction: quota + receipt + queue are one checkpoint. */
  consume(contextId: string, operationId: string, input: Pick<SupplierDraft, "items">): string {
    const parts: Array<{ id: string; qty: number }> = [];
    const requested = new Map<string, number>();
    for (const item of input.items) {
      const key = `${item.product_id}:${item.variant_color?.trim() ?? ""}`;
      requested.set(key, (requested.get(key) ?? 0) + item.qty);
    }
    for (const [key, qty] of requested) {
      let remaining = qty;
      const rows = this.store.all(
        "SELECT * FROM device_stock WHERE scope=? AND frozen=0 AND quantity>used+returned ORDER BY rowid",
        [contextId],
      );
      for (const row of rows) {
        if (`${String(row.product_id)}:${String(row.color)}` !== key) continue;
        const used = Math.min(remaining, Number(row.quantity) - Number(row.used) - Number(row.returned));
        if (!used) continue;
        this.store.run("UPDATE device_stock SET used=used+? WHERE id=?", [used, String(row.id)]);
        parts.push({ id: String(row.id), qty: used });
        remaining -= used;
        if (!remaining) break;
      }
      if (remaining)
        throw new Error(
          "حصة هذا الجهاز لا تكفي للكمية أو اللون. احجز مخزوناً أونلاين قبل اعتماد البيع بدون نت.",
        );
    }
    stockPartsSchema.parse(parts);
    const counter =
      Number(this.store.one("SELECT value FROM metadata WHERE key='receipt-counter'")?.value ?? 0) + 1;
    if (!Number.isSafeInteger(counter)) throw new Error("تعذّر إنشاء رقم بيع محلي.");
    this.store.run("INSERT OR REPLACE INTO metadata VALUES ('receipt-counter',?)", [String(counter)]);
    const device = String(this.store.one("SELECT value FROM metadata WHERE key='device'")?.value);
    const number = `OFF-${device.replaceAll("-", "")}-${String(counter).padStart(6, "0")}`;
    this.store.run("INSERT INTO operation_reservations VALUES (?,?,?)", [
      operationId,
      JSON.stringify(parts),
      number,
    ]);
    return number;
  }
}
