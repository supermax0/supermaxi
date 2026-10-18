import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeProfile(profile: string) {
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-product-settings-")
  )
    throw Error("Unsafe test cleanup");
  rmSync(profile, { recursive: true, force: true });
}

test("exchange price and channel visibility fit the product editor and save only changed fields", async () => {
  const appDir = path.resolve(__dirname, "..");
  const outputs = path.resolve(appDir, "../../tests/_artifacts/product-editor-settings-20261015");
  mkdirSync(outputs, { recursive: true });
  const stub = await startFinoraStub();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-product-settings-"));
  const app = await electron.launch({
    args: [appDir],
    cwd: appDir,
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  try {
    const page = await app.firstWindow();
    const login = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await login.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await login.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await login.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await login.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page
      .getByRole("navigation", { name: "النوافذ" })
      .getByRole("button", { name: "المنتجات", exact: true })
      .click();
    await page.getByRole("button", { name: "إجراءات شاشة LG 50 إنش" }).click();
    await page.getByRole("menuitem", { name: "تعديل", exact: true }).click();
    const sheet = page.getByRole("dialog", { name: "تعديل منتج" });
    await expect(sheet.getByLabel("سعر الاستبدال", { exact: true })).toHaveValue("300,000");
    for (const width of [1536, 1180, 1024]) {
      await app.evaluate(({ BrowserWindow }, size) => {
        const window = BrowserWindow.getAllWindows()[0];
        window?.setMinimumSize(800, 600);
        window?.setContentSize(size, 850);
      }, width);
      expect(await page.evaluate(() => innerWidth)).toBe(width);
      await sheet.getByLabel("سعر الاستبدال", { exact: true }).scrollIntoViewIfNeeded();
      await expect(sheet.getByLabel("سعر الاستبدال", { exact: true })).toBeInViewport();
      await page.screenshot({ path: path.join(outputs, `pricing-${width}.png`) });
      await sheet.getByRole("switch", { name: "إظهار في المتجر", exact: true }).scrollIntoViewIfNeeded();
      await expect(sheet.getByRole("switch", { name: "إظهار في نقطة البيع", exact: true })).toBeInViewport();
      await expect(sheet.getByRole("button", { name: "حفظ التعديلات", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(outputs, `visibility-${width}.png`) });
    }
    const exchange = sheet.getByLabel("سعر الاستبدال", { exact: true });
    await exchange.focus();
    await expect(exchange).toHaveValue("300000");
    await exchange.fill("310000");
    await exchange.press("Tab");
    await expect(exchange).toHaveValue("310,000");
    await sheet.getByRole("switch", { name: "إظهار في نقطة البيع", exact: true }).click();
    await sheet.getByRole("switch", { name: "إظهار في المتجر", exact: true }).click();
    await sheet.getByRole("button", { name: "حفظ التعديلات", exact: true }).click();
    await expect(sheet).not.toBeVisible();
    const saves = stub.bodies.filter((r) => r.path === "/inventory/api/products/1/update");
    expect(saves).toHaveLength(1);
    const raw = (saves[0]?.body as { raw: string }).raw;
    for (const [key, value] of [
      ["exchange_sale_price", "310000"],
      ["pos_visible", "0"],
      ["store_visible", "0"],
    ])
      expect(raw).toContain(`name="${key}"\r\n\r\n${value}`);
    for (const key of ["buy_price", "sale_price", "opening_stock", "active"])
      expect(raw).not.toContain(`name="${key}"`);
  } finally {
    await app.close();
    await stub.close();
    removeProfile(profile);
  }
});
