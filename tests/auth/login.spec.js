import { test, expect } from "@playwright/test";
import { login, getCredentials } from "../utils/helpers.js";

test.describe("Auth — تسجيل الدخول", () => {
  test("صفحة الدخول تظهر الحقول الأساسية", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator('input[name="tenant_slug"]')).toBeVisible();
    await expect(page.locator("#username")).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.locator('form button[type="submit"].btn-login')).toBeVisible();
  });

  test("إرسال بيانات فارغة يبقى على صفحة الدخول", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[name="tenant_slug"]').fill("");
    await page.locator("#username").fill("");
    await page.locator("#password").fill("");
    await page.locator('form button[type="submit"].btn-login').click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("تسجيل دخول صالح يعيد التوجيه بعيداً عن /login", async ({
    page,
  }) => {
    const creds = getCredentials();
    await login(page, creds);
    await expect(page).not.toHaveURL(/\/login$/);
    const path = new URL(page.url()).pathname;
    expect(path === "/" || path.startsWith("/pos")).toBeTruthy();
  });
});
