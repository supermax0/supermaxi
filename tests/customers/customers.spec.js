import { test, expect } from "@playwright/test";
import { login, getCredentials } from "../utils/helpers.js";

test.describe("Customers — الزبائن", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, getCredentials());
  });

  test("صفحة الزبائن تحمّل الجدول", async ({ page }) => {
    await page.goto("/customers", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/customers\/?$/);
    await expect(page.locator("#customersTable")).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.locator("#customersTable .ag-root-wrapper")
    ).toBeVisible({ timeout: 30_000 });
  });
});
