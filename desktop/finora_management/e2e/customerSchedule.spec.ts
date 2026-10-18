import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("customer schedule preserves paid rows, saves through IPC and shows audited history at three sizes", async () => {
  test.setTimeout(120000);
  const stub = await startFinoraStub({ customers: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-schedule-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-schedule-e2e-")
  )
    throw Error("Unsafe cleanup");
  const artifacts = path.resolve(__dirname, "../../../tests/_artifacts/erp-customers");
  mkdirSync(artifacts, { recursive: true });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const cleanup = async () => {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  };
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const login = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await login.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await login.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await login.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await login.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "العملاء", exact: true }).click();
    const customers = page.getByRole("dialog", { name: "العملاء", exact: true });
    await customers.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
    const details = customers.getByRole("complementary", { name: "أحمد العميل" });
    await details.getByRole("tab", { name: "الأقساط", exact: true }).click();
    await details.getByRole("button", { name: "جدولة الخطة 1", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "جدولة الأقساط #1", exact: true });
    await expect(dialog.getByLabel("قيمة القسط 2")).toBeDisabled();
    await expect(dialog.getByLabel("استحقاق القسط 2")).toBeDisabled();
    await dialog.getByRole("button", { name: "شرح إعادة الجدولة" }).click();
    await expect(page.getByText(/تغيّر قيمة الأقساط المتبقية ومواعيدها/)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("استحقاق القسط 1").fill("2026-11-15");
    const firstAmount = dialog.getByLabel("قيمة القسط 1");
    await firstAmount.click();
    await expect(firstAmount).toHaveValue("75000");
    await firstAmount.press("Control+A");
    await firstAmount.pressSequentially("100000");
    await expect(dialog.getByRole("button", { name: "حفظ الجدولة" })).toBeDisabled();
    const thirdAmount = dialog.getByLabel("قيمة القسط 3");
    await thirdAmount.click();
    await expect(thirdAmount).toHaveValue("150000");
    await thirdAmount.press("Control+A");
    await thirdAmount.pressSequentially("125000");
    await dialog.getByLabel("سبب إعادة الجدولة").fill("طلب العميل تأجيل وتوزيع القسط المتبقي");
    await page.keyboard.press("Escape");
    const confirm = page.getByRole("dialog", { name: "تعديلات غير محفوظة" });
    await expect(confirm).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(confirm).toHaveCount(0);
    await expect(dialog.getByLabel("استحقاق القسط 1")).toHaveValue("2026-11-15");
    await dialog.getByRole("button", { name: "حفظ الجدولة" }).click();
    await expect(dialog.getByLabel("سبب إعادة الجدولة")).toHaveValue("");
    await dialog.getByText("تاريخ تعديل الجدولة (1)", { exact: true }).click();
    await expect(dialog.getByText("طلب العميل تأجيل وتوزيع القسط المتبقي", { exact: true })).toBeVisible();
    await expect(dialog.getByText(/مدير الاختبار/)).toBeVisible();
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, dimensions) => {
          const win = BrowserWindow.getAllWindows()[0];
          win?.setMinimumSize(900, 650);
          win?.setSize(dimensions.width, dimensions.height);
        },
        { width, height },
      );
      await expect(dialog.getByRole("button", { name: "حفظ الجدولة" })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      const bounds = await dialog.boundingBox();
      const viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
      expect((bounds?.y ?? 0) + (bounds?.height ?? 0)).toBeLessThanOrEqual(viewport.height);
      expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(viewport.width);
      await page.screenshot({ path: path.join(artifacts, `schedule-${width}.png`) });
    }
    await dialog.getByRole("button", { name: "إغلاق الجدولة" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(details).toBeVisible();
    await details.getByRole("button", { name: "جدولة الخطة 1", exact: true }).click();
    await expect(dialog.getByLabel("استحقاق القسط 1")).toHaveValue("2026-11-15");
    await expect(dialog.getByLabel("قيمة القسط 1")).toHaveValue("100,000");
    const commands = stub.bodies.filter((row) => row.path.endsWith("/plans/1/schedule"));
    expect(commands).toHaveLength(1);
    expect(commands[0]?.body).toMatchObject({
      revision: "d".repeat(64),
      installments: [
        { id: 1, date: "2026-11-15", total: 100000 },
        { id: 2, date: "2026-10-10", total: 75000 },
        { id: 3, date: "2026-12-01", total: 125000 },
      ],
    });
    expect(errors).toEqual([]);
  } catch (error) {
    await cleanup();
    throw error;
  }
  await cleanup();
});
