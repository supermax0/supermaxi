import { app, BrowserWindow, dialog, safeStorage } from "electron";
import { promises as fs } from "node:fs";
import { randomBytes, randomUUID } from "node:crypto";
import path from "node:path";
import { z } from "zod";
import { getServerUrl } from "./config";
import { sendFinoraNetworkRequest } from "./finoraHttp";
import { getOfflineEngine, getOfflineStore, activateOfflineSlot } from "./offlineRuntime";
import { OfflineEngine } from "./offlineEngine";
import { OfflineDatabase, atomicWrite } from "./offlineDatabase";
import { openBackup, sealBackup, BACKUP_LIMIT } from "./backupCrypto";
import { exportScoped, importScoped, portableSchema, restoreBlocked } from "./portableStore";

const passwordSchema = z.string().min(12).max(256);
let busy = false;
export async function backupProfile(parent: BrowserWindow, action: "export" | "restore", raw: unknown) {
  const password = passwordSchema.parse(raw);
  if (busy) throw Error("توجد عملية نسخ أو استعادة جارية");
  busy = true;
  try {
    const server = await getServerUrl();
    if (!server) throw Error("حدد خادم FINORA أولاً");
    if (action === "export") {
      const engine = await getOfflineEngine(sendFinoraNetworkRequest),
        context = engine.backupContext();
      const store = await getOfflineStore();
      const result = await dialog.showSaveDialog(parent, {
        title: "حفظ نسخة FINORA المشفّرة",
        defaultPath: `FINORA-${new Date().toISOString().slice(0, 10)}.finorabackup`,
        filters: [{ name: "FINORA encrypted backup", extensions: ["finorabackup"] }],
      });
      if (result.canceled || !result.filePath) return { saved: false };
      const data = await exportScoped(store, server, context.id, context.session.permissions);
      await atomicWrite(result.filePath, await sealBackup(Buffer.from(JSON.stringify(data)), password));
      return { saved: true };
    }
    if (!safeStorage.isEncryptionAvailable()) throw Error("حماية Windows غير متاحة");
    const selection = await dialog.showOpenDialog(parent, {
      title: "استعادة نسخة FINORA",
      properties: ["openFile"],
      filters: [{ name: "FINORA encrypted backup", extensions: ["finorabackup"] }],
    });
    const selected = selection.filePaths[0];
    if (selection.canceled || !selected) return { restored: false };
    if ((await fs.stat(selected)).size > BACKUP_LIMIT + 64) throw Error("حجم النسخة غير مدعوم");
    const data = portableSchema.parse(
      JSON.parse((await openBackup(await fs.readFile(selected), password)).toString("utf8")),
    );
    const answer = await dialog.showMessageBox(parent, {
      type: "warning",
      message: "استعادة النسخة المشفّرة؟",
      detail:
        "يلزم اتصال للتحقق من الحساب والفرع والصلاحيات. تبقى ملفات الجهاز الحالية محفوظة. تُجمّد حصص المخزون المستعادة حتى تُراجع المزامنة ثم تُعاد الكميات غير المستخدمة للسيرفر.",
      buttons: ["إلغاء", "استعادة النسخة"],
      defaultId: 0,
      cancelId: 0,
    });
    if (answer.response !== 1) return { restored: false };
    const slotId = randomUUID(),
      directory = path.join(app.getPath("userData"), "offline");
    const slot = { file: `slot-${slotId}.sqlite.enc`, key: `slot-${slotId}.dpapi` };
    const key = randomBytes(32);
    const candidate = await OfflineDatabase.open(
      path.join(directory, slot.file),
      key,
      path.join(__dirname, "sql-wasm.wasm"),
    );
    let committed = false;
    try {
      const engine = new OfflineEngine(candidate, server, (r) => sendFinoraNetworkRequest(r, server));
      const auth = await engine.request({ method: "GET", path: "/api/v1/desktop/auth/session" });
      if (!auth.ok || auth.source === "offline") throw Error("سجّل الدخول واتصل بالسيرفر قبل الاستعادة");
      const context = engine.backupContext();
      let previous: OfflineDatabase | null = null;
      try {
        previous = await getOfflineStore();
      } catch {
        /* Retain an unreadable slot for manual recovery. */
      }
      if (previous && restoreBlocked(previous, context.id, data.device))
        throw Error("أكمل العمليات المحلية وأعد حصص الجهاز غير المستخدمة قبل الاستعادة؛ لم تتغيّر بياناتك");
      await importScoped(candidate, data, server, context.id, context.session.permissions);
      await atomicWrite(path.join(directory, slot.key), safeStorage.encryptString(key.toString("base64")));
      await candidate.close();
      await activateOfflineSlot(slot);
      committed = true;
      return { restored: true };
    } finally {
      key.fill(0);
      if (!committed) {
        await candidate
          .close()
          .catch(() => console.warn("[backup] candidate cleanup could not close the database"));
        await fs.unlink(path.join(directory, slot.file)).catch((error: NodeJS.ErrnoException) => {
          if (error.code !== "ENOENT") console.warn("[backup] candidate cleanup failed", error.code);
        });
        await fs.unlink(path.join(directory, slot.key)).catch((error: NodeJS.ErrnoException) => {
          if (error.code !== "ENOENT") console.warn("[backup] candidate key cleanup failed", error.code);
        });
      }
    }
  } finally {
    busy = false;
  }
}
