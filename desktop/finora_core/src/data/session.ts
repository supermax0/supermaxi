import { invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import { isTauri } from "../app/native";
import type { AuthSession } from "./http";
import { tokenResponseSchema } from "./schemas";
import { CoreError } from "./source";

const SESSION_KEY = "finora-core.session";
const sessionSchema = tokenResponseSchema.omit({ expiresIn: true });
const storedSchema = z.object({ serverUrl: z.string(), session: sessionSchema });
// Rotation and logout must reach disk in order, even if several requests finish together.
let writes: Promise<void> = Promise.resolve();

export async function saveSession(serverUrl: string, session: AuthSession | null): Promise<void> {
  const payload = session ? JSON.stringify({ serverUrl, session }) : null;
  const write = writes
    .catch(() => undefined)
    .then(async () => {
      try {
        if (isTauri()) {
          await invoke("save_session", { payload });
          sessionStorage.removeItem(SESSION_KEY);
        } else if (payload) {
          // The browser preview stays tab-scoped. Never put desktop tokens in localStorage.
          sessionStorage.setItem(SESSION_KEY, payload);
        } else {
          sessionStorage.removeItem(SESSION_KEY);
        }
      } catch {
        throw new CoreError("UNKNOWN_ERROR", "تعذّر حفظ جلسة الدخول بأمان. حاول مرة ثانية.");
      }
    });
  writes = write;
  return write;
}

export async function loadSession(serverUrl: string): Promise<AuthSession | null> {
  await writes.catch(() => undefined);
  let raw: string | null;
  try {
    raw = isTauri() ? await invoke<string | null>("load_session") : sessionStorage.getItem(SESSION_KEY);
    if (!raw && isTauri()) raw = sessionStorage.getItem(SESSION_KEY); // migrate an open old version
  } catch {
    throw new CoreError("UNKNOWN_ERROR", "تعذّر قراءة جلسة الدخول المحفوظة. حاول مرة ثانية.");
  }
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    await saveSession(serverUrl, null);
    return null;
  }
  const stored = storedSchema.safeParse(value);
  if (stored.success) return stored.data.serverUrl === serverUrl ? stored.data.session : null;
  const legacy = sessionSchema.safeParse(value);
  if (legacy.success) {
    await saveSession(serverUrl, legacy.data);
    return legacy.data;
  }
  await saveSession(serverUrl, null);
  return null;
}
