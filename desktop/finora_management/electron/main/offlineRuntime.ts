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
  let names = { file: "business.sqlite.enc", key: "key.dpapi" };
  try {
    const slot = JSON.parse(await fs.readFile(path.join(directory, "current.json"), "utf8")) as {
      file: string;
      key: string;
    };
    if (!/^slot-[a-f0-9-]{36}\.sqlite\.enc$/.test(slot.file) || !/^slot-[a-f0-9-]{36}\.dpapi$/.test(slot.key))
      throw Error("مرجع بيانات الاستعادة غير صالح");
    names = slot;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  const file = path.join(directory, names.file);
  const keyFile = path.join(directory, names.key);
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
export async function flushOfflineWrites(): Promise<void> {
  if (!database) return;
  let store: OfflineDatabase;
  try {
    store = await database;
  } catch (error) {
    recordOfflineIssue(error);
    return;
  }
  await store.settled();
}
export async function getOfflineStore() {
  if (!database) database = openDatabase();
  return database;
}
export async function activateOfflineSlot(slot: { file: string; key: string }) {
  if (
    !/^slot-[a-f0-9-]{36}\.sqlite\.enc$/.test(slot.file) ||
    slot.key !== slot.file.replace(".sqlite.enc", ".dpapi")
  )
    throw Error("مرجع بيانات الاستعادة غير صالح");
  const previous = database;
  if (previous)
    await previous
      .then((store) => store.settled())
      .catch(() => console.warn("[offline] retained previous slot could not be opened or closed"));
  await atomicWrite(
    path.join(app.getPath("userData"), "offline", "current.json"),
    Buffer.from(JSON.stringify(slot)),
  );
  database = null;
  engine = null;
  engineServer = null;
  issue = null;
  // Outstanding read probes may still hold the previous store. Its files stay intact.
  if (previous)
    setTimeout(() => {
      void previous
        .then((store) => store.close())
        .catch(() => console.warn("[offline] retained previous slot could not be opened or closed"));
    }, 65_000).unref();
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
