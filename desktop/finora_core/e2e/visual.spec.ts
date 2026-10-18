import { expect, test, type Page } from "@playwright/test";

/**
 * Visual regression + responsive checks (spec §63, §64). Deterministic: no simulation, frozen clock,
 * reduced motion (the orb renders a single static frame at phase 0), CSS animations disabled.
 */
const FROZEN = "/?sim=0&frozen=2026-10-03T19:44:00Z";
const SIZES = [
  [1280, 720],
  [1366, 768],
  [1440, 900],
  [1920, 1080],
  [2560, 1440],
] as const;

const shot = (page: Page, name: string) =>
  expect(page).toHaveScreenshot(`${name}.png`, { animations: "disabled", maxDiffPixelRatio: 0.02 });

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

/** Nothing important may overflow the viewport or overlap another region. */
async function assertNoOverlap(page: Page, selectors: string[]) {
  const vp = page.viewportSize();
  if (!vp) throw new Error("viewport size unavailable");
  const boxes = [];
  for (const sel of selectors) {
    const b = await page.locator(sel).first().boundingBox();
    expect(b, `${sel} should be rendered`).not.toBeNull();
    if (!b) continue;
    expect(b.x, `${sel} left edge`).toBeGreaterThanOrEqual(0);
    expect(b.y, `${sel} top edge`).toBeGreaterThanOrEqual(0);
    expect(b.x + b.width, `${sel} right edge`).toBeLessThanOrEqual(vp.width + 0.5);
    expect(b.y + b.height, `${sel} bottom edge`).toBeLessThanOrEqual(vp.height + 0.5);
    boxes.push({ sel, ...b });
  }
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const c = boxes[j];
      if (!a || !c) continue;
      const overlap =
        a.x < c.x + c.width && c.x < a.x + a.width && a.y < c.y + c.height && c.y < a.y + a.height;
      expect(overlap, `${a.sel} overlaps ${c.sel}`).toBe(false);
    }
}

for (const [w, h] of SIZES) {
  test.describe(`${w}x${h}`, () => {
    test.use({ viewport: { width: w, height: h } });

    test("closed orb", async ({ page }) => {
      await page.goto(FROZEN);
      await expect(page.locator(".status-bubble")).toContainText("بإنتظار");
      await assertNoOverlap(page, [
        ".status-bubble",
        ".orb-hit",
        ".channel-chip.is-left",
        ".channel-chip.is-right",
        ".stage-btn.is-left",
        ".stage-btn.is-right",
      ]);
      const d = (await page.locator(".orb-hit").boundingBox())?.width ?? 0;
      expect(d).toBeGreaterThanOrEqual(220);
      expect(d).toBeLessThanOrEqual(360);
      await shot(page, `orb-${w}x${h}`);
    });

    test("open workspace", async ({ page }) => {
      await page.goto(FROZEN);
      await page.locator(".orb-hit").click();
      await expect(page.locator(".chat-head h2")).toHaveText("أحمد علي");
      await page.waitForTimeout(900); // let the morph settle
      await assertNoOverlap(page, [".ws-list", ".ws-chat", ".ws-profile"]);
      const chat = await page.locator(".ws-chat").boundingBox();
      expect(chat?.width ?? 0, "conversation panel must stay usable").toBeGreaterThan(420);
      await shot(page, `workspace-${w}x${h}`);
    });
  });
}

test.describe("states", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("approval card", async ({ page }) => {
    await page.goto("/?cycle=2&cycleDelay=200&frozen=2026-10-03T19:44:00Z");
    await expect(page.locator(".approval-bar")).toBeVisible({ timeout: 9000 });
    await page.locator(".stage-btn.is-left").click();
    await expect(page.locator(".sheet .approval-card")).toBeVisible();
    await page.waitForTimeout(700);
    await expect(page.locator(".sheet")).toHaveScreenshot("activity-approval.png", {
      animations: "disabled",
    });
  });

  test("settings", async ({ page }) => {
    await page.goto(FROZEN);
    await page.locator(".stage-btn.is-right").click();
    await page.waitForTimeout(700);
    await expect(page.locator(".sheet")).toHaveScreenshot("settings.png", { animations: "disabled" });
  });

  test("long names and messages do not break the layout", async ({ page }) => {
    await page.goto(FROZEN);
    await page.locator(".orb-hit").click();
    await page
      .getByRole("list", { name: "المحادثات" })
      .getByRole("button")
      .filter({ hasText: "Al-Rashed" })
      .click();
    await expect(page.locator(".chat-head h2")).toHaveText("Al-Rashed Co.");
    // mixed-direction content renders in its own direction
    await expect(page.locator(".msg-text").filter({ hasText: "detailed quote" })).toHaveAttribute(
      "dir",
      "auto",
    );
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
  });
});
