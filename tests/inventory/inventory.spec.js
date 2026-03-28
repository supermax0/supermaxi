import { test, expect } from "@playwright/test";
import { login, createProduct, getCredentials } from "../utils/helpers.js";

test.describe("Inventory — المخزون", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await login(page, getCredentials());
  });

  test("إضافة منتج من صفحة الإضافة ثم ظهوره عند البحث في نقطة البيع", async ({
    page,
  }) => {
    const name = `e2e-prod-${Date.now()}`;
    await createProduct(page, { name, buyPrice: 5000, salePrice: 7500 });
    await page.goto("/pos", { waitUntil: "domcontentloaded" });
    await page.locator("#searchProduct").fill(name);
    await expect(
      page.locator("#productResults .pos-product-item").first()
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("#productResults")).toContainText(name);
  });
});
