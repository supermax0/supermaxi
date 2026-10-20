import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { closeIsolatedApp } from "./closeIsolatedApp";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeProfile(directory: string) {
  if (
    path.dirname(path.resolve(directory)) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-clock-")
  )
    throw Error("Unsafe test cleanup");
  rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}

test("company clock updates existing order cells and survives a renderer reload", async () => {
  const stub = await startFinoraStub({ workspace: true });
  const directory = mkdtempSync(path.join(os.tmpdir(), "finora-clock-"));
  const app = await electron.launch({
    ...(process.env.FINORA_E2E_EXECUTABLE ? { executablePath: process.env.FINORA_E2E_EXECUTABLE } : {}),
    args: process.env.FINORA_E2E_EXECUTABLE ? [] : [path.resolve(__dirname, "..")],
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: directory },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم", { exact: true }).fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور", { exact: true }).fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "الطلبات", exact: true }).click();
    await expect(page.getByText("07/10 01:25 م", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    await page.getByRole("button", { name: "المظهر والاختصارات", exact: true }).click();
    await page.getByRole("radio", { name: /24 ساعة/ }).click();
    await expect(page.getByRole("radio", { name: /24 ساعة/ })).toHaveAttribute("aria-checked", "true");
    await page.getByRole("button", { name: "إغلاق الإعدادات", exact: true }).click();
    await expect(page.getByText("07/10 13:25", { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("clock-24.png") });
    await page.reload();
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    await page.getByRole("button", { name: "المظهر والاختصارات", exact: true }).click();
    await expect(page.getByRole("radio", { name: /24 ساعة/ })).toHaveAttribute("aria-checked", "true");
    expect(errors).toEqual([]);
  } finally {
    await closeIsolatedApp(app);
    await stub.close();
    removeProfile(directory);
  }
});
