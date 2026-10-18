import { expect, test, type Page } from "@playwright/test";

/**
 * FINORA CORE web-shell E2E (development data source; spec §62).
 * Login (scenario 1) and tenant creation (13) need the backend (Phase 6/8) and are not covered here.
 */

const bubble = (page: Page) => page.locator(".status-bubble");
const openOrb = async (page: Page) => {
  await page.locator(".orb-hit").click();
  await expect(page.locator(".workspace:not(.is-closed)")).toBeVisible();
};

test("opens in the closed orb state", async ({ page }) => {
  await page.goto("/?sim=0");
  await expect(page.locator(".orb-hit")).toBeVisible();
  await expect(page.locator(".orb-canvas canvas")).toBeAttached();
  await expect(bubble(page)).toContainText("بإنتظار الرسائل الجديدة");
  await expect(page.locator(".workspace")).toHaveClass(/is-closed/);
  await expect(page.getByText("DEV DATA")).toBeVisible();
});

test("an incoming message drives the orb through execution states", async ({ page }) => {
  await page.goto("/?cycle=0&cycleDelay=300");
  await expect(bubble(page)).toContainText("Instagram", { timeout: 4000 });
  await expect(bubble(page)).toContainText("يحلل احتياجات المتجر", { timeout: 6000 });
  await expect(bubble(page)).toContainText("تم الرد ✓", { timeout: 8000 });
  await expect(bubble(page)).toContainText("بإنتظار الرسائل الجديدة", { timeout: 6000 });
});

test("orb opens into the workspace with conversation, chat and customer profile", async ({ page }) => {
  await page.goto("/?sim=0");
  await openOrb(page);
  const rows = page.getByRole("list", { name: "المحادثات" }).getByRole("button");
  await expect(rows).toHaveCount(7);
  await expect(rows.first()).toHaveAttribute("aria-current", "true");
  await expect(page.locator(".chat-head h2")).toHaveText("أحمد علي");
  await expect(page.getByRole("heading", { name: "ملف العميل" })).toBeVisible();
  await expect(page.locator(".cp-facts")).toContainText("عيادة أسنان");

  await rows.filter({ hasText: "د. سارة" }).click();
  await expect(page.locator(".chat-head h2")).toHaveText("د. سارة");
  await expect(page.locator(".cp-facts")).toContainText("غير محدد");
});

test("human takeover, manual reply and AI resume", async ({ page }) => {
  await page.goto("/?sim=0");
  await openOrb(page);
  await page.getByRole("button", { name: /استلام المحادثة/ }).click();
  const box = page.getByLabel("نص الرسالة");
  await expect(box).toBeVisible();
  await box.fill("أهلاً دكتور أحمد، معك فريق FINORA");
  await box.press("Enter");
  const sent = page.locator(".msg.from-human").last();
  await expect(sent).toContainText("معك فريق FINORA");
  await expect(sent.getByLabel(/وصلت|أُرسلت/)).toBeVisible();
  await expect(page.locator(".msg-system").last()).toContainText("استلم Super Admin");

  await page.getByRole("button", { name: /إعادة تشغيل FINORA CORE/ }).click();
  await expect(page.locator(".composer.is-locked")).toBeVisible();
  await expect(page.locator(".msg-system").last()).toContainText("إعادة تشغيل");
});

test("approval workflow from the orb stage", async ({ page }) => {
  await page.goto("/?cycle=2&cycleDelay=300");
  const bar = page.locator(".approval-bar");
  await expect(bar).toBeVisible({ timeout: 9000 });
  await expect(bar).toContainText("حد الوكيل 15%");
  await expect(bubble(page)).toContainText("بانتظار موافقتك");
  await bar.getByRole("button", { name: "موافقة", exact: true }).click();
  await expect(bar).toBeHidden();
  await expect(bubble(page)).toContainText("يطبق الخصم المعتمد");
  await page.locator(".stage-btn.is-left").click();
  await page.getByRole("tab", { name: "الموافقات" }).click();
  await expect(page.locator(".timeline")).toContainText("تمت الموافقة");
});

test("closing the workspace returns to the orb and preserves the selection", async ({ page }) => {
  await page.goto("/?sim=0");
  await openOrb(page);
  await page
    .getByRole("list", { name: "المحادثات" })
    .getByRole("button")
    .filter({ hasText: "شركة النور" })
    .click();
  await page.getByRole("button", { name: "العودة إلى FINORA CORE" }).click();
  await expect(page.locator(".workspace")).toHaveClass(/is-closed/);
  await expect(page.locator(".orb-hit")).toBeVisible();
  await openOrb(page);
  await expect(page.locator(".chat-head h2")).toHaveText("شركة النور");
});

test("Escape closes the customer panel, then the workspace", async ({ page }) => {
  await page.goto("/?sim=0");
  await openOrb(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "ملف العميل" })).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.locator(".workspace")).toHaveClass(/is-closed/);
});

test("kill switch requires a reason and is reflected in the titlebar", async ({ page }) => {
  await page.goto("/?sim=0");
  await page.locator(".stage-btn.is-right").click();
  const pause = page.getByRole("button", { name: /إيقاف كل الأتمتة/ });
  await expect(pause).toBeDisabled();
  await page.getByLabel("سبب الإيقاف").fill("صيانة مجدولة");
  await pause.click();
  await expect(page.locator(".live-pill")).toHaveText(/Paused/);
  await page.getByRole("button", { name: /استئناف الأتمتة/ }).click();
  await expect(page.locator(".live-pill")).toHaveText(/Live/);
});

test("offline state is shown honestly", async ({ page, context }) => {
  await page.goto("/?sim=0");
  await expect(bubble(page)).toContainText("بإنتظار");
  await context.setOffline(true);
  await expect(page.getByRole("alert").filter({ hasText: "Offline" })).toBeVisible();
  await expect(bubble(page)).toContainText("غير متصل");
  await context.setOffline(false);
  await expect(bubble(page)).not.toContainText("غير متصل");
});

test("orb stays aligned with its hit-area after repeated open/close", async ({ page }) => {
  await page.goto("/?sim=0");
  const stage = page.locator(".stage");
  const canvas = page.locator(".orb-canvas canvas");
  // The orb canvas is lazy-loaded; wait until R3F has sized it to the stage before taking the baseline.
  await expect
    .poll(async () => Math.round((await canvas.boundingBox())?.width ?? 0))
    .toBe(Math.round((await stage.boundingBox())?.width ?? -1));
  const before = await canvas.boundingBox();
  for (let i = 0; i < 3; i++) {
    await page.locator(".orb-hit").click();
    await page.waitForTimeout(250); // close mid-morph too
    await page.getByRole("button", { name: "العودة إلى FINORA CORE" }).click();
    await page.waitForTimeout(900);
  }
  const after = await canvas.boundingBox();
  const s = await stage.boundingBox();
  expect(after?.width).toBeCloseTo(s?.width ?? 0, 0);
  expect(after?.height).toBeCloseTo(s?.height ?? 0, 0);
  expect(after?.width).toBeCloseTo(before?.width ?? 0, 0);
  const css = await canvas.evaluate((c) => ({ w: parseFloat(c.style.width), h: parseFloat(c.style.height) }));
  expect(css.w).toBeCloseTo(s?.width ?? 0, 0);
  expect(css.h).toBeCloseTo(s?.height ?? 0, 0);
});
