import { expect } from "@playwright/test";

/**
 * @param {import('@playwright/test').Page} page
 * @param {{ tenantSlug: string; username: string; password: string }} creds
 */
export async function login(page, { tenantSlug, username, password }) {
  await page.goto("/login");
  await page.locator('input[name="tenant_slug"]').fill(tenantSlug);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.locator('form button[type="submit"].btn-login').click();
  await page.waitForURL(
    (url) => !String(url.pathname).endsWith("/login"),
    { timeout: 35_000 }
  );
}

/**
 * @param {import('@playwright/test').Page} page
 * @param {{ name: string; buyPrice?: number; salePrice?: number; openingStock?: number }} opts
 */
export async function createProduct(page, opts) {
  const { name, buyPrice = 1000, salePrice = 1500, openingStock = 10 } = opts;
  await page.goto("/inventory/add");
  await page.locator('input[name="name"]').fill(name);
  await page.locator("#opening_stock").fill(String(openingStock));
  await page.locator("#buy_price").fill(String(buyPrice));
  await page.locator("#sale_price").fill(String(salePrice));
  await page
    .locator('button[name="submit_action"][value="save"]')
    .click();
  await page.waitForURL(
    (url) =>
      /\/inventory\/?$/.test(url.pathname) &&
      !url.pathname.includes("/add"),
    { timeout: 25_000 }
  );
}

/**
 * نقطة بيع: زبون جديد + بحث منتج بالاسم + تنفيذ الطلب (يتجنب حوار الطباعة).
 * إن وُجد `#pageSelect` يجب اختيار بيج أو «لا يوجد بيج».
 *
 * @param {import('@playwright/test').Page} page
 * @param {{ productName: string; customerName: string; customerPhone: string }} opts
 */
export async function createOrderViaPos(page, opts) {
  const { productName, customerName, customerPhone } = opts;
  await page.goto("/pos", { waitUntil: "domcontentloaded" });

  await page.getByRole("button", { name: /إضافة زبون/ }).first().click();
  await page.locator("#name").fill(customerName);
  await page.locator("#phone").fill(customerPhone);
  await page.getByRole("button", { name: /حفظ الزبون/ }).click();
  await expect(page.locator("#selectedCustomer")).toContainText(customerName, {
    timeout: 20_000,
  });

  await page.locator("#searchProduct").fill(productName);
  await expect(
    page.locator("#productResults .pos-product-item").first()
  ).toBeVisible({ timeout: 20_000 });
  await page.locator("#productResults .pos-product-item").first().click();
  await expect(page.locator("#orderItems")).not.toBeEmpty({ timeout: 10_000 });

  await page.getByRole("button", { name: /تنفيذ الطلب/ }).click();
  const pageSelect = page.locator("#pageSelect");
  if (await pageSelect.count()) {
    await pageSelect.selectOption("no_page");
  }
  await page.getByRole("button", { name: /تأكيد الطلب/ }).click();

  await expect(page.locator("#selectedCustomer")).toContainText("لم يتم", {
    timeout: 25_000,
  });
}

/**
 * افتراضيات تطوير: مستخدم admin (دور admin في الجلسة).
 * أقفال القائمة (مشتريات، موردين، …) تُحدَّد بالخطة — شغّل:
 *   py scripts/dev_full_access.py supermax
 * يمكن تجاوز القيم بـ PLAYWRIGHT_* في البيئة.
 */
const DEFAULT_E2E_CREDS = {
  tenantSlug: "supermax",
  username: "admin",
  // نفس كلمة مرور التطوير السابقة؛ لمزامنة DB: py scripts/create_dev_user.py supermax admin dev12345
  password: "dev12345",
};

export function getCredentials() {
  return {
    tenantSlug:
      process.env.PLAYWRIGHT_TENANT_SLUG || DEFAULT_E2E_CREDS.tenantSlug,
    username: process.env.PLAYWRIGHT_USERNAME || DEFAULT_E2E_CREDS.username,
    password: process.env.PLAYWRIGHT_PASSWORD || DEFAULT_E2E_CREDS.password,
  };
}
