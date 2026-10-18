import { expect, test } from "@playwright/test";

test("operator saves response settings, previews safely and connects Meta", async ({ page }, testInfo) => {
  let config = {
    provider: "cloud", cloudModel: "", localUrl: "http://127.0.0.1:11434", localModel: "", timeoutSeconds: 15,
    replyMode: "automatic", language: "auto", tone: "friendly", replyLength: "short", minimumConfidence: 0.7, instructions: "",
  };
  const operator = { id: 1, username: "owner", role: "super_admin", permissions: ["settings.manage", "conversations.view", "audit.view"] };
  let connects = 0;
  await page.addInitScript((value) => {
    sessionStorage.setItem("finora-core.session", JSON.stringify({ accessToken: "fake", refreshToken: "fake", operator: value }));
  }, operator);
  // Every API request is intercepted: this browser test cannot reach Meta or send a real message.
  await page.route("http://127.0.0.1:5019/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = { items: [] };
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "GET, POST, PATCH" } });
      return;
    }
    if (path.endsWith("/status")) body = {
      environment: "production", channels: { instagram: "disconnected", facebook: "disconnected" }, automationPaused: false,
      shadowMode: config.replyMode === "review", agent: { state: "idle", label: null, conversationId: null, channel: null },
      conversationCount: 0, houseConfigured: true, devLoopback: false,
    };
    if (path.endsWith("/settings/agent")) {
      if (route.request().method() === "PATCH") config = route.request().postDataJSON() as typeof config;
      body = { config, cloudKeyConfigured: true, cloudKeySource: "server", resolvedCloudModel: "server-model" };
    }
    if (path.endsWith("/settings/agent/preview")) body = { text: "هلا بيك، شنو نوع نشاطكم؟", source: "model", model: "test-model", needsHuman: false, reason: null, fallback: null };
    if (path.endsWith("/settings/knowledge")) body = {
      featureCount: 162, guideCount: 63, publishedCount: 0, categories: [], note: "الشرح يعتمد على أدلة الاستخدام الموثقة",
      results: new URL(route.request().url()).searchParams.get("q") ? [{ id: "guide:inventory.add", title: "إضافة منتج للمخزون", text: "1. افتح المخزون ثم إضافة منتج.\n2. أدخل البيانات واحفظ.", kind: "guide", businessType: null, source: "reviewed" }] : [],
    };
    if (path.endsWith("/settings/meta")) body = { houseConfigured: true, appId: "12345", secretConfigured: true, webhookUrl: "https://finora.test/meta/webhook", channels: [] };
    if (path.endsWith("/settings/meta/connect")) {
      expect(route.request().postDataJSON()).toMatchObject({ appId: "12345", userToken: "fake-user-token" });
      connects += 1;
      body = { pagesFound: 1, warningsCount: 0, message: "تم الربط" };
    }
    if (path.endsWith("/events/stream")) {
      await route.abort(); // This workflow tests settings, independently of the separately tested realtime stream.
      return;
    }
    await route.fulfill({ json: body, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/?gl=0", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "الإعدادات" });
  await expect(dialog).toHaveCSS("opacity", "1");
  await expect(dialog.getByRole("button", { name: "ردود العملاء", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("settings-home.png") });
  await dialog.getByRole("button", { name: "الذكاء الاصطناعي", exact: true }).click();
  await expect(dialog.getByLabel("مصدر الذكاء")).toBeVisible();
  await expect(dialog.getByLabel("طريقة الرد")).not.toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("ai-settings.png") });
  await dialog.getByRole("button", { name: "كل الإعدادات" }).click();
  await dialog.getByRole("button", { name: "ردود العملاء", exact: true }).click();
  await expect(dialog.getByLabel("مصدر الذكاء")).not.toBeVisible();
  await expect(dialog.getByLabel("طريقة الرد")).toHaveValue("automatic");
  await page.screenshot({ path: testInfo.outputPath("agent-settings.png") });
  await dialog.getByRole("button", { name: "إعدادات فينورا المقترحة" }).click();
  await dialog.getByText("تجربة الرد قبل الإرسال", { exact: true }).click();
  await expect(dialog.getByRole("button", { name: "تجربة الرد" })).toBeDisabled();
  await dialog.getByRole("button", { name: "حفظ إعدادات الرد" }).click();
  await expect(dialog.getByRole("button", { name: "تجربة الرد" })).toBeEnabled();
  expect(config.replyMode).toBe("review");
  await dialog.getByRole("button", { name: "تجربة الرد" }).click();
  await expect(dialog.getByLabel("نتيجة تجربة الرد")).toContainText("شنو نوع نشاطكم؟");
  await dialog.getByRole("button", { name: "كل الإعدادات" }).click();
  await dialog.getByRole("button", { name: "ربط Meta", exact: true }).click();
  await expect(dialog.getByLabel("Meta App ID")).toHaveValue("12345");
  await page.screenshot({ path: testInfo.outputPath("meta-settings.png") });
  await dialog.getByLabel("Meta User Access Token").fill("fake-user-token");
  await dialog.getByRole("button", { name: "ربط ومزامنة الصفحات" }).click();
  await expect(dialog.getByLabel("Meta User Access Token")).toHaveValue("");
  expect(connects).toBe(1);
  await dialog.getByRole("button", { name: "كل الإعدادات" }).click();
  await dialog.getByRole("button", { name: "معرفة النظام", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText("162 ميزة");
  await dialog.getByLabel("ابحث عن ميزة أو طريقة استخدامها").fill("شلون اضيف منتج؟");
  await dialog.getByRole("button", { name: "بحث في معرفة النظام" }).click();
  await expect(dialog.getByRole("heading", { name: "إضافة منتج للمخزون" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("knowledge-settings.png") });
  await dialog.getByRole("button", { name: "كل الإعدادات" }).click();
  await page.setViewportSize({ width: 1280, height: 720 });
  await dialog.getByRole("button", { name: "النظام والأتمتة", exact: true }).click();
  await expect(dialog.getByLabel("سبب الإيقاف")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "إيقاف كل الأتمتة", exact: true })).toBeDisabled();
  expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
});
