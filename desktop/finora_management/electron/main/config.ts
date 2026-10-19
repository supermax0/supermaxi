/** Non-secret client settings (server address, last tenant/username). Never passwords or cookies. */
import { promises as fs } from "node:fs";
import path from "node:path";
import { app } from "electron";
import { z } from "zod";
import { serverUrlSchema, type DesktopConfig } from "../../shared/ipc";
import { atomicWrite } from "./offlineDatabase";

const storedSchema = z.object({
  serverUrl: z.string().nullable().catch(null),
  lastTenantSlug: z.string().nullable().catch(null),
  lastUsername: z.string().nullable().catch(null),
});
type StoredConfig = z.infer<typeof storedSchema>;

const EMPTY: StoredConfig = { serverUrl: null, lastTenantSlug: null, lastUsername: null };

function configPath(): string {
  return path.join(app.getPath("userData"), "finora-management.json");
}

let cache: StoredConfig | null = null;

/** Installed copies start pointed at FINORA's production server (changeable on the sign-in screen). */
const DEFAULT_SERVER_URL = "https://www.finora.company";

function envServerUrl(): string | null {
  const raw = process.env.FINORA_SERVER_URL ?? (app.isPackaged ? DEFAULT_SERVER_URL : undefined);
  if (!raw) return null;
  const parsed = serverUrlSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}

async function load(): Promise<StoredConfig> {
  if (cache) return cache;
  try {
    const parsed = storedSchema.safeParse(JSON.parse(await fs.readFile(configPath(), "utf8")));
    cache = parsed.success ? parsed.data : { ...EMPTY };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      console.warn("[config] unreadable settings file, starting fresh");
    }
    cache = { ...EMPTY };
  }
  const stored = cache.serverUrl ? serverUrlSchema.safeParse(cache.serverUrl) : null;
  if (!stored?.success) cache.serverUrl = envServerUrl();
  return cache;
}

async function save(next: StoredConfig): Promise<void> {
  const file = configPath();
  await atomicWrite(file, Buffer.from(JSON.stringify(next, null, 2), "utf8"));
  cache = next;
}

function toPublic(config: StoredConfig): DesktopConfig {
  return { ...config, appVersion: app.getVersion() };
}

export async function getConfig(): Promise<DesktopConfig> {
  return toPublic(await load());
}

export async function getServerUrl(): Promise<string | null> {
  return (await load()).serverUrl;
}

export async function setServerUrl(serverUrl: string): Promise<DesktopConfig> {
  const next = { ...(await load()), serverUrl };
  await save(next);
  return toPublic(next);
}

export async function rememberIdentity(tenantSlug: string, username: string): Promise<DesktopConfig> {
  const next = { ...(await load()), lastTenantSlug: tenantSlug, lastUsername: username };
  await save(next);
  return toPublic(next);
}
