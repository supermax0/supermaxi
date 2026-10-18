import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeTestProfile(profile: string) {
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-order-collection-e2e-")
  )
    throw new Error("Unsafe test cleanup");
  rmSync(profile, { recursive: true, force: true });
}

test("order split collection keeps help, layout and a single payment submission", async () => {
  const appDir = path.resolve(__dirname, "..");
  const stub = await startFinoraStub({ orderEditing: true, orderCollection: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-order-collection-e2e-"));
  const app = await electron.launch({
    args: [appDir],
    cwd: appDir,
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const login = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await login.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await login.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await login.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await login.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page
      .getByRole("navigation", { name: "النوافذ" })
      .getByRole("button", { name: "الطلبات", exact: true })
      .click();
    await page.getByRole("button", { name: "إجراءات الطلب 10045" }).click();
    await page.getByRole("menuitem", { name: "عرض التفاصيل" }).click();
    await page
      .getByRole("complementary", { name: "الطلب #10045" })
      .getByRole("button", { name: /^تسديد/ })
      .click();
    const dialog = page.getByRole("dialog", { name: "تسديد الطلب #10045" });
    await dialog.getByRole("button", { name: "شرح تسديد الطلب" }).click();
    await expect(page.getByRole("note")).toContainText("تحدّث أقساطه");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("note")).not.toBeVisible();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("radio", { name: /تسديد جزئي/ }).click();
    const partial = dialog.getByLabel("مبلغ التسديد الجزئي", { exact: true });
    await partial.click();
    await partial.press("Control+a");
    await partial.pressSequentially("75000");
    await expect(partial).toHaveValue("75000");
    await dialog.getByRole("button", { name: "تقسيم الدفعة على أكثر من حساب" }).click();
    await dialog.getByLabel("حساب الدفعة 1", { exact: true }).selectOption("4");
    await dialog.getByLabel("حساب الدفعة 2", { exact: true }).selectOption("5");
    const first = dialog.getByLabel("مبلغ الدفعة 1", { exact: true });
    await first.click();
    await expect(first).toHaveValue("75000");
    await first.press("Control+a");
    await first.pressSequentially("30000");
    const second = dialog.getByLabel("مبلغ الدفعة 2", { exact: true });
    await second.click();
    await second.press("Control+a");
    await second.pressSequentially("45000");
    await expect(second).toHaveValue("45000");
    await expect(first).toHaveValue("30,000");
    const submit = dialog.getByRole("button", { name: /تأكيد التسديد/ });
    for (const width of [1536, 1180, 1024]) {
      await app.evaluate(
        ({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0]?.setContentSize(size, 850),
        width,
      );
      await expect(submit).toBeEnabled();
      await expect(submit).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(appDir, "test-results", `order-collection-${width}.png`) });
    }
    expect(stub.bodies.filter((entry) => entry.path === "/orders/payment")).toHaveLength(0);
    await submit.click();
    await expect(dialog).not.toBeVisible();
    const payments = stub.bodies.filter((entry) => entry.path === "/orders/payment");
    expect(payments).toHaveLength(1);
    expect(payments[0]?.body).toMatchObject({
      id: 10045,
      payment: "جزئي",
      paid_amount: 75000,
      payment_allocations: [
        { treasury_account_id: 4, amount: 30000 },
        { treasury_account_id: 5, amount: 45000 },
      ],
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    await stub.close();
    removeTestProfile(profile);
  }
});
