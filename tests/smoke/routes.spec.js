import { test, expect } from "@playwright/test";
import { login, getCredentials } from "../utils/helpers.js";

/**
 * جولة سريعة: المسارات الأساسية لا تعيد لصفحة الدخول.
 */
test.describe("Smoke — مسارات بعد الدخول", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, getCredentials());
  });

  const paths = ["/", "/inventory", "/orders", "/customers"];

  for (const path of paths) {
    test(`GET ${path} ليس login`, async ({ page }) => {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      await expect(page).not.toHaveURL(/\/login/);
    });
  }
});
