import { app } from "electron";
import https from "node:https";
import os from "node:os";
import path from "node:path";
import { promises as fs, createReadStream, createWriteStream } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { pipeline } from "node:stream/promises";
import { Transform } from "node:stream";
import { spawn } from "node:child_process";
import { z } from "zod";
import { getServerUrl } from "./config";
import { replaceFile } from "./offlineDatabase";

export const updateManifest = z
  .object({
    version: z.string().regex(/^\d{1,4}\.\d{1,4}\.\d{1,4}$/),
    filename: z
      .string()
      .regex(/^FINORA-Management-Setup-\d+\.\d+\.\d+-Windows-(?:10-11-x64|7-8-10-11)\.exe$/),
    platform: z.string(),
    size_bytes: z
      .number()
      .int()
      .positive()
      .max(500 * 1024 * 1024),
    sha256: z.string().regex(/^[a-f0-9]{64}$/),
  })
  .strict();
type Manifest = z.infer<typeof updateManifest>;
export function newerVersion(latest: string, current: string) {
  const a = latest.split(".").map(Number),
    b = current.split(".").map(Number);
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return (a[i] ?? 0) > (b[i] ?? 0);
  return false;
}
function legacy() {
  return Number(os.release().split(".")[0]) < 10 || process.arch === "ia32";
}
function read(url: URL) {
  return new Promise<import("node:http").IncomingMessage>((resolve, reject) => {
    const request = https.get(url, { timeout: 30_000 }, (response) => {
      if (response.statusCode !== 200) {
        response.resume();
        reject(Error(`تعذّر تنزيل التحديث (${response.statusCode})`));
      } else resolve(response);
    });
    request.on("timeout", () => request.destroy(Error("انتهت مهلة تنزيل التحديث")));
    request.on("error", reject);
  });
}
let selected: { manifest: Manifest; origin: string } | null = null;
let downloaded: { file: string; manifest: Manifest; origin: string } | null = null;
let downloading: Promise<{ ready: boolean }> | null = null;
async function origin() {
  const server = await getServerUrl();
  if (!server || new URL(server).protocol !== "https:") throw Error("التحديثات تتطلب خادم HTTPS موثوقاً");
  return new URL(server).origin;
}
export async function checkUpdate() {
  const host = await origin();
  const response = await read(
    new URL(`/static/downloads/finora-management${legacy() ? "-legacy" : ""}.json`, host),
  );
  const parts: Buffer[] = [];
  let length = 0;
  for await (const chunk of response) {
    length += Buffer.byteLength(chunk);
    if (length > 16_384) {
      response.destroy();
      throw Error("ملف التحديث غير صالح");
    }
    parts.push(Buffer.from(chunk));
  }
  const manifest = updateManifest.parse(JSON.parse(Buffer.concat(parts).toString("utf8")));
  if (
    !manifest.filename.includes(`-${manifest.version}-`) ||
    legacy() !== manifest.filename.includes("7-8-10-11")
  )
    throw Error("التحديث لا يطابق نظام Windows");
  const available = newerVersion(manifest.version, app.getVersion());
  selected = available ? { manifest, origin: host } : null;
  return { current: app.getVersion(), latest: manifest.version, available, size: manifest.size_bytes };
}
async function download() {
  if (!selected || selected.origin !== (await origin())) throw Error("افحص التحديثات أولاً");
  const choice = selected;
  const directory = path.join(app.getPath("userData"), "updates");
  await fs.mkdir(directory, { recursive: true });
  const file = path.join(directory, choice.manifest.filename),
    temporary = `${file}.${randomUUID()}.part`;
  let length = 0;
  const hash = createHash("sha256");
  const verify = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      length += chunk.length;
      if (length > choice.manifest.size_bytes) callback(Error("حجم التحديث لا يطابق الملف المعلن"));
      else {
        hash.update(chunk);
        callback(null, chunk);
      }
    },
  });
  try {
    const response = await read(new URL(`/static/downloads/${choice.manifest.filename}`, choice.origin));
    await pipeline(response, verify, createWriteStream(temporary, { flags: "wx", mode: 0o600 }));
    if (length !== choice.manifest.size_bytes || hash.digest("hex") !== choice.manifest.sha256)
      throw Error("فشل التحقق من سلامة التحديث؛ لم يُشغّل الملف");
    const handle = await fs.open(temporary, "r+");
    try {
      await handle.sync();
    } finally {
      await handle.close();
    }
    await replaceFile(temporary, file);
    downloaded = { file, ...choice };
    return { ready: true };
  } finally {
    await fs.unlink(temporary).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== "ENOENT") console.warn("[updates] temporary cleanup failed", error.code);
    });
  }
}
export function downloadUpdate() {
  if (!downloading)
    downloading = download().finally(() => {
      downloading = null;
    });
  return downloading;
}
export async function launchUpdate() {
  const ready = downloaded;
  if (!ready || ready.origin !== (await origin())) throw Error("نزّل التحديث وتحقق منه أولاً");
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(ready.file)) hash.update(chunk);
  if (
    (await fs.stat(ready.file)).size !== ready.manifest.size_bytes ||
    hash.digest("hex") !== ready.manifest.sha256
  )
    throw Error("تغيّر ملف التحديث؛ أعد تنزيله");
  await new Promise<void>((resolve, reject) => {
    const child = spawn(ready.file, [], { detached: true, stdio: "ignore", windowsHide: true });
    child.once("error", reject);
    child.once("spawn", () => {
      child.unref();
      resolve();
    });
  });
}
