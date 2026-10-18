import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeProfile(profile: string) {
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-product-colors-e2e-")
  )
    throw new Error("Unsafe test cleanup");
  rmSync(profile, { recursive: true, force: true });
}

test("product colors fit the native editor and save through multipart IPC", async () => {
  const appDir = path.resolve(__dirname, "..");
  const stub = await startFinoraStub();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-product-colors-e2e-"));
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
    await sheet.getByRole("checkbox", { name: "هذا المنتج عنده خيارات" }).check();
    for (const color of ["أبيض", "أسود", "ستيل"]) {
      await sheet.getByLabel("قيمة اللون", { exact: true }).fill(color);
      await sheet.getByRole("button", { name: "إضافة خيار", exact: true }).click();
    }
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5mQAAAAASUVORK5CYII=",
      "base64",
    );
    await sheet
      .getByLabel("صورة أبيض", { exact: true })
      .setInputFiles({ name: "white.png", mimeType: "image/png", buffer: png });
    await sheet
      .getByLabel("صورة أسود", { exact: true })
      .setInputFiles({ name: "black.png", mimeType: "image/png", buffer: png });
    await expect(sheet.getByAltText("صورة أبيض", { exact: true })).toBeVisible();
    await expect(sheet.getByAltText("صورة أسود", { exact: true })).toBeVisible();
    await expect(sheet.getByText(/المطلوب توزيع/)).toContainText("28 قطعة");
    for (const width of [1536, 1180]) {
      await app.evaluate(
        ({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0]?.setContentSize(size, 850),
        width,
      );
      await sheet.getByLabel("قيمة اللون").scrollIntoViewIfNeeded();
      await expect(sheet.getByRole("button", { name: "حفظ التعديلات", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(appDir, "test-results", `product-colors-${width}.png`) });
    }
    await sheet.getByRole("button", { name: "حفظ التعديلات", exact: true }).click();
    await expect(sheet).not.toBeVisible();
    const saves = stub.bodies.filter((r) => r.path === "/inventory/api/products/1/update");
    expect(saves).toHaveLength(1);
    const raw = (saves[0]?.body as { raw: string }).raw;
    expect(raw).toContain('name="product_options"');
    expect(raw).toContain('"expected_stock":28');
    expect(raw).toContain('"name":"ستيل"');
    expect(raw).toContain('name="color_images"');
    expect(raw).toContain('name="color_image_0"; filename="upload.png"');
    expect(raw).toContain('name="color_image_1"; filename="upload.png"');
    expect(raw).not.toContain('name="opening_stock"');
  } finally {
    await app.close();
    await stub.close();
    removeProfile(profile);
  }
});
