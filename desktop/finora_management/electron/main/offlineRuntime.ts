import { randomBytes } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { app, safeStorage } from "electron";
import type { OfflineStatus } from "../../shared/offline";
import { getServerUrl } from "./config";
import { atomicWrite, OfflineDatabase } from "./offlineDatabase";
import { OfflineEngine } from "./offlineEngine";
import type { FinoraRequest, FinoraResponse } from "../../shared/ipc";

let database: Promise<OfflineDatabase> | null = null;
let engine: OfflineEngine | null = null;
let engineServer: string | null = null;
let issue: string | null = null;
export const unavailableStatus = (): OfflineStatus => ({
  available: false,
  lastVerifiedAt: null,
  lastCachedAt: null,
  pending: 0,
  conflicts: 0,
  syncing: false,
  error: issue,
  operations: [],
});

async function openDatabase(): Promise<OfflineDatabase> {
  if (!safeStorage.isEncryptionAvailable())
    throw new Error("حماية Windows غير متاحة؛ لم يُفعّل تخزين بيانات الأوفلاين.");
  const directory = path.join(app.getPath("userData"), "offline");
  const file = path.join(directory, "business.sqlite.enc");
  const keyFile = path.join(directory, "key.dpapi");
  let key: Buffer;
  try {
    key = Buffer.from(safeStorage.decryptString(await fs.readFile(keyFile)), "base64");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT")
      throw new Error("تعذّر فتح مفتاح الأوفلاين؛ بياناتك محفوظة وتحتاج إلى استعادة المفتاح.");
    try {
      await fs.access(file);
      throw new Error("مفتاح الأوفلاين مفقود؛ لم تُحذف قاعدة البيانات.");
    } catch (missing) {
      if ((missing as NodeJS.ErrnoException).code !== "ENOENT") throw missing;
    }
    key = randomBytes(32);
    await atomicWrite(keyFile, safeStorage.encryptString(key.toString("base64")));
  }
  if (key.length !== 32) throw new Error("مفتاح بيانات الأوفلاين غير صالح.");
  return OfflineDatabase.open(file, key, path.join(__dirname, "sql-wasm.wasm"));
}

export async function getOfflineEngine(
  sender: (r: FinoraRequest, expectedServer?: string) => Promise<FinoraResponse>,
): Promise<OfflineEngine> {
  const server = await getServerUrl();
  if (!server) throw new Error("حدد خادم FINORA أولاً.");
  if (!database) database = openDatabase();
  const store = await database;
  if (!engine || engineServer !== server) {
    engine = new OfflineEngine(store, server, (request) => sender(request, server));
    engineServer = server;
    try {
      await fs.access(path.join(app.getPath("userData"), "offline", "access.disabled"));
      await engine.deactivate();
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  return engine;
}
export function recordOfflineIssue(error: unknown): void {
  issue = error instanceof Error ? error.message : "تعذّر فتح البيانات المحلية؛ لم تُحذف بياناتك.";
  engine?.recordIssue(error);
}
export async function deactivateOffline(): Promise<void> {
  await atomicWrite(
    path.join(app.getPath("userData"), "offline", "access.disabled"),
    Buffer.from("signed out"),
  );
  if (engine) await engine.deactivate();
}
export async function enableOfflineAccess(): Promise<void> {
  await fs
    .unlink(path.join(app.getPath("userData"), "offline", "access.disabled"))
    .catch((error: NodeJS.ErrnoException) => {
      if (error.code !== "ENOENT") throw error;
    });
}
