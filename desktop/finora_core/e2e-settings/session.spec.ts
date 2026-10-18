import { expect, test } from "@playwright/test";

test("desktop IPC restores after closing the window, rotates expired access and clears on logout", async ({ context }) => {
  const operator = { id: 1, username: "owner", role: "super_admin", permissions: ["settings.manage", "conversations.view", "audit.view"] };
  let saved: string | null = null;
  let access = "test-access-1";
  let refresh = "test-refresh-1";
  let expired = false;
  let loginCalls = 0;
  let refreshCalls = 0;
  let writes = 0;
  await context.exposeBinding("sessionStoreForTest", (_source, command: string, payload: string | null) => {
    // Simulate the native store independently of the window. Real DPAPI is tested by the Rust tests.
    if (command === "save_session") { saved = payload; writes += 1; return null; }
    if (command === "load_session") return saved;
    throw new Error("Unexpected session command");
  });
  await context.addInitScript(() => {
    let callback = 1;
    const win = window as unknown as {
      sessionStoreForTest: (command: string, payload: string | null) => Promise<string | null>;
      __TAURI_INTERNALS__: unknown;
      __TAURI_EVENT_PLUGIN_INTERNALS__: unknown;
    };
    win.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      transformCallback: () => callback++,
      invoke: async (command: string, args: { payload?: string | null }) => {
        if (command === "save_session" || command === "load_session") return win.sessionStoreForTest(command, args.payload ?? null);
        if (command === "plugin:window|is_maximized") return false;
        if (command === "plugin:event|listen") return callback++;
        if (command === "plugin:event|unlisten") return null;
        throw new Error(`Unexpected native command: ${command}`);
      },
    };
    win.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: () => undefined };
  });
  await context.route("http://127.0.0.1:5019/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const headers = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "GET, POST, PATCH" };
    if (request.method() === "OPTIONS") { await route.fulfill({ status: 204, headers }); return; }
    if (path.endsWith("/auth/login")) {
      loginCalls += 1;
      await route.fulfill({ json: { accessToken: access, refreshToken: refresh, operator, expiresIn: 900 }, headers }); return;
    }
    if (path.endsWith("/auth/refresh")) {
      expect(request.postDataJSON()).toEqual({ refreshToken: refresh });
      refreshCalls += 1;
      access = "test-access-2"; refresh = "test-refresh-2"; expired = false;
      await route.fulfill({ json: { accessToken: access, refreshToken: refresh, operator, expiresIn: 900 }, headers }); return;
    }
    if (expired || request.headers().authorization !== `Bearer ${access}`) {
      await route.fulfill({ status: 401, json: { error: { code: "AUTH_ERROR", message: "expired" } }, headers }); return;
    }
    if (path.endsWith("/events/stream")) { await route.abort(); return; }
    let body: unknown = { items: [] };
    if (path.endsWith("/status")) body = { environment: "production", channels: { instagram: "disconnected", facebook: "disconnected" }, automationPaused: false, agent: { state: "idle", label: null, conversationId: null, channel: null }, conversationCount: 0, houseConfigured: true, devLoopback: false };
    if (path.endsWith("/auth/logout")) body = { ok: true };
    await route.fulfill({ json: body, headers });
  });
  const first = await context.newPage();
  await first.goto("/?gl=0", { waitUntil: "domcontentloaded" });
  await first.getByLabel("اسم المستخدم", { exact: true }).fill("test-owner");
  await first.getByLabel("كلمة المرور", { exact: true }).fill("test-only-password");
  await first.getByRole("button", { name: "دخول", exact: true }).click();
  await expect(first.getByRole("button", { name: "الإعدادات", exact: true })).toBeVisible();
  expect(saved).toContain("test-refresh-1");
  expect(await first.evaluate(() => sessionStorage.getItem("finora-core.session"))).toBeNull();
  await first.close();
  expired = true;
  const second = await context.newPage();
  await second.goto("/?gl=0", { waitUntil: "domcontentloaded" });
  await expect(second.getByRole("button", { name: "الإعدادات", exact: true })).toBeVisible();
  await expect.poll(() => saved).toContain("test-refresh-2");
  expect(loginCalls).toBe(1);
  expect(refreshCalls).toBe(1);
  expect(writes).toBe(2);
  await second.getByRole("button", { name: "الإعدادات", exact: true }).click();
  await second.getByRole("button", { name: "الحساب", exact: true }).click();
  await second.getByRole("button", { name: "تسجيل الخروج", exact: true }).click();
  await expect(second.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();
  expect(saved).toBeNull();
  await second.close();
  const third = await context.newPage();
  await third.goto("/?gl=0", { waitUntil: "domcontentloaded" });
  await expect(third.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();
});
