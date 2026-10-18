import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthSession } from "./http";
import { loadSession, saveSession } from "./session";

const native = vi.hoisted(() => ({ enabled: true, stored: null as string | null, invoke: vi.fn() }));
vi.mock("../app/native", () => ({ isTauri: () => native.enabled }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: native.invoke }));
const base = "https://www.finora.company";
const session: AuthSession = {
  accessToken: "test-access",
  refreshToken: "test-refresh",
  operator: { id: 1, username: "owner", role: "super_admin", permissions: [] },
};

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  native.enabled = true;
  native.stored = null;
  native.invoke.mockReset().mockImplementation(async (command: string, args?: { payload: string | null }) => {
    if (command === "save_session" && args) native.stored = args.payload;
    if (command === "load_session") return native.stored;
  });
});

describe("encrypted desktop session", () => {
  it("restores after webview storage is destroyed and never stores tokens in localStorage", async () => {
    await saveSession(base, session);
    sessionStorage.clear(); // Closing the window destroys the old tab-scoped storage.
    expect(await loadSession(base)).toEqual(session);
    expect(sessionStorage.length).toBe(0);
    expect(localStorage.length).toBe(0);
    expect(native.invoke).toHaveBeenCalledWith("save_session", {
      payload: JSON.stringify({ serverUrl: base, session }),
    });
  });

  it("binds a saved session to its server", async () => {
    await saveSession(base, session);
    expect(await loadSession("https://another.finora.test")).toBeNull();
    expect(await loadSession(base)).toEqual(session);
  });

  it("migrates the previous open-window session into native storage", async () => {
    sessionStorage.setItem("finora-core.session", JSON.stringify(session));
    expect(await loadSession(base)).toEqual(session);
    expect(sessionStorage.length).toBe(0);
    expect(native.stored).toContain("test-refresh");
  });

  it("writes rotated tokens before clearing on logout", async () => {
    const saved = saveSession(base, session);
    const rotated = saveSession(base, { ...session, refreshToken: "rotated" });
    const cleared = saveSession(base, null);
    await Promise.all([saved, rotated, cleared]);
    expect(await loadSession(base)).toBeNull();
    expect(native.stored).toBeNull();
  });

  it("reports storage failures instead of claiming the session was saved", async () => {
    native.invoke.mockRejectedValueOnce(new Error("test storage failure"));
    await expect(saveSession(base, session)).rejects.toMatchObject({ code: "UNKNOWN_ERROR" });
    await saveSession(base, session); // A failed write does not poison future saves.
    expect(await loadSession(base)).toEqual(session);
  });

  it("does not erase the encrypted session on a temporary read failure", async () => {
    await saveSession(base, session);
    native.invoke.mockRejectedValueOnce(new Error("test read failure"));
    await expect(loadSession(base)).rejects.toMatchObject({ code: "UNKNOWN_ERROR" });
    expect(await loadSession(base)).toEqual(session);
  });

  it("discards invalid saved content", async () => {
    native.stored = "invalid-json";
    expect(await loadSession(base)).toBeNull();
    expect(native.stored).toBeNull();
  });

  it("keeps browser previews tab-scoped", async () => {
    native.enabled = false;
    await saveSession(base, session);
    expect(await loadSession(base)).toEqual(session);
    expect(localStorage.length).toBe(0);
    expect(native.invoke).not.toHaveBeenCalled();
    await saveSession(base, null);
    expect(await loadSession(base)).toBeNull();
  });
});
