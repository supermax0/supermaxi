import { app, safeStorage } from "electron";
import { promises as fs } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { z } from "zod";
import { atomicWrite } from "./offlineDatabase";
import { getServerUrl } from "./config";
import { sendFinoraNetworkRequest } from "./finoraHttp";
import {
  DEFAULT_LOCAL_ASSISTANT,
  historyRowSchema,
  localAssistantSettingsSchema,
  localHistorySchema,
  localSaveSchema,
  type LocalAssistantSettings,
} from "../../shared/localAssistant";

const file = (name: string) => path.join(app.getPath("userData"), name);
const hash = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const tokenFile = (settings: LocalAssistantSettings) =>
  file(`assistant-token-${hash([settings.provider, settings.host, settings.port])}.bin`);
export async function assistantSettings(): Promise<LocalAssistantSettings> {
  try {
    return localAssistantSettingsSchema.parse(
      JSON.parse(await fs.readFile(file("local-assistant.json"), "utf8")),
    );
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { ...DEFAULT_LOCAL_ASSISTANT };
    throw Error("تعذر قراءة إعدادات المساعد المحلي. أعد حفظ إعدادات الربط.");
  }
}
async function readEncrypted(name: string): Promise<string | null> {
  try {
    const data = await fs.readFile(name);
    if (!safeStorage.isEncryptionAvailable()) throw Error("التشفير المحلي غير متاح في Windows");
    return safeStorage.decryptString(data);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw Error("تعذر فتح البيانات المشفرة للمساعد على هذا الجهاز");
  }
}
async function writeEncrypted(name: string, text: string): Promise<void> {
  if (!safeStorage.isEncryptionAvailable())
    throw Error("التشفير المحلي غير متاح. استخدم محادثة الجلسة الحالية بدون حفظ.");
  await atomicWrite(name, safeStorage.encryptString(text));
}
export async function assistantToken(settings: LocalAssistantSettings): Promise<string> {
  return (await readEncrypted(tokenFile(settings))) ?? "";
}
export async function assistantPublicSettings() {
  const settings = await assistantSettings();
  return { settings, hasToken: !!(await assistantToken(settings)) };
}
export async function configureAssistant(input: unknown) {
  const value = localSaveSchema.parse(input);
  if (value.clearToken) await fs.rm(tokenFile(value.settings), { force: true });
  if (value.token) await writeEncrypted(tokenFile(value.settings), value.token);
  await atomicWrite(file("local-assistant.json"), Buffer.from(JSON.stringify(value.settings), "utf8"));
  return assistantPublicSettings();
}
export async function assistantHistoryScope(): Promise<string> {
  const response = await sendFinoraNetworkRequest({ method: "GET", path: "/api/v1/desktop/auth/session" });
  if (!response.ok) throw Error("حفظ المحادثة يحتاج جلسة فينورا موثقة واتصالاً بالخادم");
  const session = z
    .object({
      session: z.object({
        tenant: z.object({ id: z.number(), slug: z.string() }),
        user: z.object({ id: z.number() }),
        branch: z.object({ id: z.number() }).nullable().optional(),
        branch_scope: z.string(),
        permissions: z.array(z.string()),
      }),
    })
    .parse(response.data).session;
  return hash([
    await getServerUrl(),
    session.tenant.id,
    session.tenant.slug,
    session.user.id,
    session.branch_scope,
    session.branch?.id,
    [...session.permissions].sort(),
  ]);
}
export async function loadAssistantHistory() {
  const scope = await assistantHistoryScope();
  if (!(await assistantSettings()).remember) return { scope, rows: [] };
  const data = await readEncrypted(file(`assistant-history-${scope}.bin`));
  return { scope, rows: data ? z.array(historyRowSchema).max(40).parse(JSON.parse(data)) : [] };
}
export async function saveAssistantHistory(input: unknown) {
  const { expectedScope, rows } = localHistorySchema.parse(input);
  const scope = await assistantHistoryScope();
  if (expectedScope !== scope) throw Error("تغير الحساب أو الفرع. أعد فتح محادثة المساعد.");
  const name = file(`assistant-history-${scope}.bin`);
  if (!rows.length) {
    await fs.rm(name, { force: true });
    return;
  }
  if ((await assistantSettings()).remember) await writeEncrypted(name, JSON.stringify(rows));
}
