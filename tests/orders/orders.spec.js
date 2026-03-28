import { test, expect } from "@playwright/test";
import { login, getCredentials } from "../utils/helpers.js";

test.describe("Orders — الطلبات", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await login(page, getCredentials());
  });

  test("صفحة الطلبات تحمّل البطاقات الإحصائية والجدول", async ({
    page,
  }) => {
    await page.goto("/orders");
    await expect(page).toHaveURL(/\/orders\/?$/);
    await expect(page.locator("#statTotal")).toBeVisible();
    await expect(page.locator("#statSales")).toBeVisible();
    await expect(page.locator("#statPending")).toBeVisible();
    await expect(page.locator("#statReturns")).toBeVisible();
    await expect(page.locator("#ordersTable .ag-root-wrapper")).toBeVisible({
      timeout: 30_000,
    });
  });
});
