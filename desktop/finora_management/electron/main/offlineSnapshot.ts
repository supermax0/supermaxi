import { createHash, randomUUID } from "node:crypto";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";
import {
  snapshotManifestSchema,
  snapshotPageSchema,
  snapshotRowsSchema,
  type SnapshotManifest,
  type SnapshotDataset,
  type SnapshotStatus,
} from "../../shared/snapshot";
import type { FinoraSession } from "../../src/api/finora/schemas";
import { OfflineDatabase } from "./offlineDatabase";

export type SnapshotRow = Record<string, unknown> & { id: number };
type Context = { id: string; session: FinoraSession };
export class OfflineSnapshot {
  private running: Promise<void> | null = null;
  constructor(
    private store: OfflineDatabase,
    private context: () => Context | null,
    private sender: (request: FinoraRequest) => Promise<FinoraResponse>,
  ) {}

  active() {
    const context = this.context();
    const row =
      context && this.store.one("SELECT * FROM snapshots WHERE scope=? AND state='active'", [context.id]);
    return row
      ? {
          scope: String(row.scope),
          id: String(row.id),
          stale: !!row.stale,
          manifest: snapshotManifestSchema.parse(JSON.parse(String(row.manifest))),
        }
      : null;
  }
  rows(name: SnapshotDataset): SnapshotRow[] {
    const active = this.active();
    return active
      ? this.store
          .all(
            "SELECT body FROM snapshot_records WHERE scope=? AND generation=? AND dataset=? ORDER BY position",
            [active.scope, active.id, name],
          )
          .map((row) => JSON.parse(String(row.body)) as SnapshotRow)
      : [];
  }
  has(name: SnapshotDataset): boolean {
    return this.active()?.manifest.datasets.some((d) => d.name === name) ?? false;
  }
  status(): SnapshotStatus {
    const active = this.active();
    const context = this.context();
    const staging =
      context && this.store.one("SELECT * FROM snapshots WHERE scope=? AND state='staging'", [context.id]);
    const manifest = staging?.manifest
      ? snapshotManifestSchema.parse(JSON.parse(String(staging.manifest)))
      : null;
    const count = staging
      ? Number(
          this.store.one("SELECT COUNT(*) AS count FROM snapshot_records WHERE scope=? AND generation=?", [
            String(staging.scope),
            String(staging.id),
          ])?.count ?? 0,
        )
      : 0;
    return {
      capturedAt: active?.manifest.captured_at ?? null,
      downloaded: staging ? count : (active?.manifest.datasets.reduce((n, d) => n + d.total, 0) ?? 0),
      total: (manifest ?? active?.manifest)?.datasets.reduce((n, d) => n + d.total, 0) ?? 0,
      downloading: !!this.running,
      resumable: !!staging,
      stale: active?.stale ?? false,
      datasets: (active?.manifest.datasets ?? []).map(({ name, total }) => ({ name, total })),
      error: staging?.error ? String(staging.error) : null,
    };
  }
  download(): Promise<void> {
    if (this.running) return this.running;
    this.running = this.perform().finally(() => {
      this.running = null;
    });
    return this.running;
  }
  async reset(): Promise<void> {
    if (this.running) throw new Error("انتظر اكتمال تنزيل البيانات الجاري.");
    const context = this.context();
    if (!context) throw new Error("سجّل الدخول قبل بدء تنزيل جديد.");
    await this.store.write(() => {
      this.assertScope(context.id);
      this.store.run(
        "DELETE FROM snapshot_records WHERE scope=? AND generation IN (SELECT id FROM snapshots WHERE scope=? AND state='staging')",
        [context.id, context.id],
      );
      this.store.run("DELETE FROM snapshots WHERE scope=? AND state='staging'", [context.id]);
    });
  }
  private assertScope(scope: string, manifest?: SnapshotManifest): void {
    const current = this.context();
    if (current?.id !== scope) throw new Error("تغيّر المستخدم أو الفرع؛ توقف تنزيل النسخة.");
    if (manifest) this.validateManifest(manifest, current);
  }
  private validateManifest(manifest: SnapshotManifest, context: Context): void {
    if (
      manifest.tenant_slug !== context.session.tenant.slug ||
      manifest.user_id !== context.session.user.id ||
      manifest.branch_id !== (context.session.branch?.id ?? null) ||
      manifest.branch_scope !== (context.session.branch_scope ?? "branch") ||
      JSON.stringify(manifest.permissions.slice().sort()) !==
        JSON.stringify(context.session.permissions.slice().sort())
    )
      throw new Error("نسخة التنزيل لا تطابق المستخدم والفرع والصلاحيات الحالية.");
  }
  private async perform(): Promise<void> {
    await this.store.settled();
    const context = this.context();
    if (!context) throw new Error("سجّل الدخول أونلاين قبل تنزيل البيانات.");
    let staging = this.store.one("SELECT * FROM snapshots WHERE scope=? AND state='staging'", [context.id]);
    if (
      staging?.manifest &&
      snapshotManifestSchema.parse(JSON.parse(String(staging.manifest))).expires_at <= Date.now()
    ) {
      await this.store.write(() => {
        this.store.run("DELETE FROM snapshot_records WHERE scope=? AND generation=?", [
          context.id,
          String(staging?.id),
        ]);
        this.store.run("DELETE FROM snapshots WHERE scope=? AND id=?", [context.id, String(staging?.id)]);
      });
      staging = undefined;
    }
    const id = staging ? String(staging.id) : randomUUID();
    if (!staging)
      await this.store.write(() => {
        this.assertScope(context.id);
        this.store.run("INSERT INTO snapshots(scope,id,state) VALUES (?,?,'staging')", [context.id, id]);
      });
    try {
      const result = await this.sender({
        method: "POST",
        path: "/api/v1/desktop/snapshots",
        timeoutMs: 60_000,
        body: {
          id,
          device_id: String(this.store.one("SELECT value FROM metadata WHERE key='device'")?.value),
        },
      });
      this.assertScope(context.id);
      if (!result.ok) {
        if (result.failure === "http" && result.status === 410) {
          await this.store.write(() => {
            this.store.run("DELETE FROM snapshot_records WHERE scope=? AND generation=?", [context.id, id]);
            this.store.run("DELETE FROM snapshots WHERE scope=? AND id=?", [context.id, id]);
          });
        }
        throw new Error(
          "تعذّر تجهيز النسخة من السيرفر؛ البيانات السابقة محفوظة. أعد التنزيل عند عودة الاتصال.",
        );
      }
      const manifest = snapshotManifestSchema.parse(result.data);
      this.validateManifest(manifest, context);
      if (manifest.id !== id) throw new Error("معرّف نسخة التنزيل غير مطابق.");
      if (staging?.manifest && String(staging.manifest) !== JSON.stringify(manifest))
        throw new Error("تغيّرت صفحات نسخة التنزيل؛ لم تُستبدل بياناتك.");
      await this.store.write(() => {
        this.assertScope(context.id);
        this.store.run("UPDATE snapshots SET manifest=?,error=NULL WHERE scope=? AND id=?", [
          JSON.stringify(manifest),
          context.id,
          id,
        ]);
      });
      for (const dataset of manifest.datasets) {
        let cursor = Number(
          this.store.one(
            "SELECT COUNT(*) AS count FROM snapshot_records WHERE scope=? AND generation=? AND dataset=?",
            [context.id, id, dataset.name],
          )?.count ?? 0,
        );
        while (cursor < dataset.total) {
          this.assertScope(context.id, manifest);
          const response = await this.sender({
            method: "GET",
            path: `/api/v1/desktop/snapshots/${id}/${dataset.name}`,
            query: { cursor },
            timeoutMs: 30_000,
          });
          this.assertScope(context.id, manifest);
          if (!response.ok) throw new Error("انقطع تنزيل البيانات؛ تقدّمك محفوظ ويمكن استئنافه.");
          const page = snapshotPageSchema.parse(response.data);
          if (
            page.id !== id ||
            page.dataset !== dataset.name ||
            page.cursor !== cursor ||
            page.next_cursor !== Math.min(cursor + dataset.page_size, dataset.total) ||
            createHash("sha256").update(page.rows_json).digest("hex") !== page.digest
          )
            throw new Error("فشل التحقق من صفحة التنزيل؛ بقيت النسخة القديمة محفوظة.");
          const rows = snapshotRowsSchema.parse(JSON.parse(page.rows_json));
          if (rows.length !== page.next_cursor - cursor)
            throw new Error("صفحة التنزيل ناقصة؛ لم تُنشر النسخة الجديدة.");
          await this.store.write(() => {
            this.assertScope(context.id, manifest);
            rows.forEach((row, index) =>
              this.store.run("INSERT INTO snapshot_records VALUES (?,?,?,?,?,?)", [
                context.id,
                id,
                dataset.name,
                cursor + index,
                row.id,
                JSON.stringify(row),
              ]),
            );
          });
          cursor = page.next_cursor;
        }
      }
      await this.store.write(() => {
        this.assertScope(context.id, manifest);
        for (const dataset of manifest.datasets) {
          const count = this.store.one(
            "SELECT COUNT(*) AS total,COUNT(DISTINCT record_id) AS unique_count FROM snapshot_records WHERE scope=? AND generation=? AND dataset=?",
            [context.id, id, dataset.name],
          );
          if (Number(count?.total) !== dataset.total || Number(count?.unique_count) !== dataset.total)
            throw new Error("مجموعة التنزيل ناقصة أو تحتوي معرّفات مكررة.");
        }
        this.store.run("DELETE FROM snapshot_records WHERE scope=? AND generation<>?", [context.id, id]);
        this.store.run("DELETE FROM snapshots WHERE scope=? AND id<>?", [context.id, id]);
        this.store.run("UPDATE snapshots SET state='active',error=NULL WHERE scope=? AND id=?", [
          context.id,
          id,
        ]);
        this.store.run("DELETE FROM responses WHERE scope=?", [context.id]);
      });
    } catch (error) {
      await this.store.write(() =>
        this.store.run("UPDATE snapshots SET error=? WHERE scope=? AND id=?", [
          error instanceof Error ? error.message : "تعذّر التنزيل",
          context.id,
          id,
        ]),
      );
      throw error;
    }
  }
}
