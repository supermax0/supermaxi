import { test, expect } from "@playwright/test";
import { login, getCredentials } from "../utils/helpers.js";

test.describe("Dashboard — لوحة التحكم", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, getCredentials());
  });

  test("بعد الدخول كمسؤول: إحصائيات لوحة التحكم والمخططات", async ({
    page,
  }) => {
    await page.goto("/");
    if (await page.locator(".dashboard-welcome-title").isVisible()) {
      test.skip(
        true,
        "يتطلّب حساب admin (الكاشير يرى شاشة ترحيب بدون مخططات)"
      );
    }
    await expect(page.locator("#cashBalance")).toBeVisible();
    await expect(page.locator("#sales")).toBeVisible();
    await expect(page.locator("#periodProfit")).toBeVisible();
    await expect(page.locator("#inventory")).toBeVisible();
    await expect(page.locator("#c_all")).toBeVisible();
    await expect(page.locator("canvas#salesChart")).toBeAttached();
    await expect(page.locator("canvas#profitChart")).toBeAttached();
    await expect(page.locator("canvas#statusChart")).toBeAttached();
  });
});
