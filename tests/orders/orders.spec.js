import { test, expect } from "@playwright/test";
import {
  login,
  getCredentials,
  createProduct,
  createOrderViaPos,
} from "../utils/helpers.js";

test.describe("Orders — الطلبات", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await page.context().addInitScript(() => {
      window.print = () => {};
    });
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

  test("إنشاء طلب من نقطة البيع ثم ظهوره في قائمة الطلبات", async ({
    page,
  }) => {
    const stamp = Date.now();
    const productName = `e2e-order-${stamp}`;
    const customerName = `E2E زبون ${stamp}`;
    const customerPhone = `0790${String(stamp).slice(-7)}`;

    await createProduct(page, { name: productName, buyPrice: 1000, salePrice: 2000 });
    await createOrderViaPos(page, { productName, customerName, customerPhone });

    await page.goto("/orders", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#ordersTable .ag-root-wrapper")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator("#ordersTable")).toContainText(customerName, {
      timeout: 45_000,
    });
  });
});
