import { test, expect } from "@playwright/test";
import { login, createProduct, getCredentials } from "../utils/helpers.js";

test.describe("Inventory — المخزون", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await login(page, getCredentials());
  });

  test("إضافة منتج من صفحة الإضافة ثم ظهوره في القائمة", async ({
    page,
  }) => {
    const name = `e2e-prod-${Date.now()}`;
    await createProduct(page, { name, buyPrice: 5000, salePrice: 7500 });
    await page.goto("/inventory", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#productsTable")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(".inventory-page")).toContainText(name, {
      timeout: 45_000,
    });
  });
});
