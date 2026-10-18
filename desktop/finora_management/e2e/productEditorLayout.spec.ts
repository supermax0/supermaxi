import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeProfile(profile: string) {
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-editor-layout-")
  )
    throw Error("Unsafe test cleanup");
  rmSync(profile, { recursive: true, force: true });
}

test("product editor keeps its heading and save controls fixed while scrolling and saving", async () => {
  const appDir = path.resolve(__dirname, "..");
  const profile = mkdtempSync(path.join(tmpdir(), "finora-editor-layout-"));
  const outputs = path.resolve(appDir, "../../tests/_artifacts/product-editor-layout");
  mkdirSync(outputs, { recursive: true });
  const stub = await startFinoraStub({ productSaveDelayMs: 1200, failFirstProductSave: true });
  const app = await electron.launch({
    ...(process.env.FINORA_LAYOUT_EXECUTABLE ? { executablePath: process.env.FINORA_LAYOUT_EXECUTABLE } : {}),
    args: process.env.FINORA_LAYOUT_EXECUTABLE ? [] : [appDir],
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
    await page.getByRole("button", { name: "منتج جديد", exact: true }).click();
    const sheet = page.getByRole("dialog", { name: "منتج جديد", exact: true });
    await sheet.getByLabel("اسم المنتج", { exact: true }).fill("اختبار التمرير");
    for (const [width, height] of [
      [1536, 862],
      [1180, 700],
      [1024, 600],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, size) => {
          const window = BrowserWindow.getAllWindows()[0];
          window?.setMinimumSize(800, 500);
          window?.setContentSize(size.width, size.height);
        },
        { width, height },
      );
      await sheet.getByLabel("الوصف", { exact: true }).fill("نهاية النموذج");
      await sheet.getByRole("button", { name: "حفظ المنتج", exact: true }).evaluate((button) => {
        button.scrollIntoView({ block: "center" });
        (button as HTMLButtonElement).focus();
      });
      const geometry = await sheet.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const headerElement = element.querySelector("header");
        const footerElement = element.querySelector("footer");
        if (!headerElement || !footerElement) throw Error("Missing editor controls");
        const header = headerElement.getBoundingClientRect();
        const footer = footerElement.getBoundingClientRect();
        return {
          top: rect.top,
          bottom: rect.bottom,
          headerTop: header.top,
          footerBottom: footer.bottom,
          scrollTop: element.scrollTop,
          scrollHeight: element.scrollHeight,
          clientHeight: element.clientHeight,
        };
      });
      await page.screenshot({ path: path.join(outputs, `create-${width}.png`) });
      expect(geometry.scrollTop).toBe(0);
      expect(geometry.headerTop).toBeGreaterThanOrEqual(geometry.top);
      expect(Math.abs(geometry.footerBottom - geometry.bottom)).toBeLessThanOrEqual(2);
      await expect(sheet.getByRole("heading", { name: "منتج جديد", exact: true })).toBeInViewport();
      await expect(sheet.getByRole("button", { name: "حفظ المنتج", exact: true })).toBeInViewport();
    }
    await sheet.getByRole("button", { name: "حفظ المنتج", exact: true }).click();
    await expect(sheet.getByRole("button", { name: "جارٍ الحفظ…", exact: true })).toBeDisabled();
    await expect(sheet.getByRole("heading", { name: "منتج جديد", exact: true })).toBeInViewport();
    await expect(sheet.getByRole("button", { name: "جارٍ الحفظ…", exact: true })).toBeInViewport();
    await page.screenshot({ path: path.join(outputs, "saving.png") });
    await expect(sheet.getByRole("alert")).toHaveText("تعذر حفظ المنتج، حاول مجدداً.");
    await expect(sheet.getByRole("alert")).toBeInViewport();
    await expect(sheet.getByRole("button", { name: "حفظ المنتج", exact: true })).toBeEnabled();
    await expect(sheet.getByLabel("اسم المنتج", { exact: true })).toHaveValue("اختبار التمرير");
    await page.screenshot({ path: path.join(outputs, "save-error.png") });
    await sheet.getByRole("button", { name: "حفظ وإضافة آخر", exact: true }).click();
    await expect(sheet.getByLabel("اسم المنتج", { exact: true })).toHaveValue("");
    await expect(sheet.getByLabel("اسم المنتج", { exact: true })).toBeInViewport();
    await expect(sheet.getByRole("heading", { name: "منتج جديد", exact: true })).toBeInViewport();
    await sheet.getByLabel("اسم المنتج", { exact: true }).fill("منتج آخر");
    await sheet.getByRole("button", { name: "حفظ المنتج", exact: true }).click();
    await expect(sheet).not.toBeVisible();
    expect(stub.bodies.filter((entry) => entry.path === "/inventory/add")).toHaveLength(3);
    await page.getByRole("button", { name: "منتج جديد", exact: true }).click();
    await expect(sheet.getByLabel("اسم المنتج", { exact: true })).toBeInViewport();
    await expect(sheet.getByLabel("اسم المنتج", { exact: true })).toHaveValue("");
  } finally {
    await app.close();
    await stub.close();
    removeProfile(profile);
  }
});
