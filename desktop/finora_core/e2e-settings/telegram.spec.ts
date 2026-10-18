import { expect, test } from "@playwright/test";

test("Telegram bot settings preserve the FINORA design and channel filter", async ({ page }, testInfo) => {
  const operator = { id: 1, username: "owner", role: "super_admin", permissions: ["settings.manage", "conversations.view", "audit.view"] };
  let channel = { houseConfigured: true, tokenConfigured: false, botId: "", username: "", name: "", active: false, status: "disconnected", webhookUrl: "", botUrl: "", lastError: null };
  let connections = 0;
  let filtered = false;
  await page.addInitScript((value) => sessionStorage.setItem("finora-core.session", JSON.stringify({ accessToken: "fake", refreshToken: "fake", operator: value })), operator);
  await page.route("http://127.0.0.1:5019/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "GET, POST, PATCH" } });
      return;
    }
    let body: unknown = { items: [] };
    if (path.endsWith("/status")) body = { environment: "production", channels: { instagram: "disconnected", facebook: "disconnected", telegram: channel.active ? "connected" : "disconnected" }, automationPaused: false,
      shadowMode: true, agent: { state: "idle", label: null, conversationId: null, channel: null }, conversationCount: 0, houseConfigured: true, devLoopback: false };
    if (path.endsWith("/settings/telegram/connect")) {
      expect(request.postDataJSON()).toEqual({ botToken: "test-bot-token" });
      connections += 1;
      channel = { ...channel, tokenConfigured: true, botId: "12345678", username: "FINORA_test_bot", name: "FINORA", active: true,
        status: "connected", webhookUrl: "https://finora.test/api/v1/finora-core/webhooks/telegram/test", botUrl: "https://t.me/FINORA_test_bot" };
    }
    if (path.includes("/settings/telegram")) body = channel;
    if (path.endsWith("/conversations") && url.searchParams.get("channel") === "telegram") filtered = true;
    if (path.endsWith("/events/stream")) { await route.abort(); return; }
    await route.fulfill({ json: body, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/?gl=0", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".channel-chip.is-telegram")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("telegram-orb.png") });
  await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "الإعدادات" });
  await expect(dialog).toHaveCSS("opacity", "1");
  await dialog.getByRole("button", { name: "بوت تلگرام", exact: true }).click();
  const token = dialog.getByLabel("رمز بوت تلگرام");
  await expect(token).toHaveAttribute("type", "password");
  await expect(dialog.getByRole("button", { name: "ربط البوت", exact: true })).toBeDisabled();
  await token.fill("test-bot-token");
  await dialog.getByRole("button", { name: "ربط البوت", exact: true }).click();
  await expect(token).toHaveValue("");
  await expect(dialog.getByRole("link", { name: "@FINORA_test_bot" })).toBeVisible();
  await dialog.getByRole("button", { name: "فحص اتصال تلگرام" }).click();
  await expect(dialog.getByRole("status")).toContainText("يعملان");
  expect(connections).toBe(1);
  await page.screenshot({ path: testInfo.outputPath("telegram-settings.png") });
  await page.setViewportSize({ width: 1280, height: 720 });
  expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("telegram-settings-1280.png") });
  await dialog.getByRole("button", { name: "إغلاق", exact: true }).click();
  await page.locator(".orb-hit").click();
  await page.getByRole("tab", { name: "Telegram", exact: true }).click();
  await expect.poll(() => filtered).toBe(true);
  await expect(page.getByRole("tab", { name: "Telegram", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".workspace")).toHaveCSS("opacity", "1");
  await expect(page.locator(".ws-list")).toHaveCSS("opacity", "1");
  expect(await page.locator(".cl-tabs").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("telegram-filter-1280.png") });
});
