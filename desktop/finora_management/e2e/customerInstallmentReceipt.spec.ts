import { readFileSync, mkdtempSync, rmSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("real invoice installment receipt data shows its allocations and explains them at desktop sizes", async () => {
  const artifacts = path.resolve(__dirname, "../../../tests/_artifacts");
  // Produced by the real, isolated finance command integration test.
  const receipt = JSON.parse(
    readFileSync(path.join(artifacts, "finance-customer-installments.json"), "utf8"),
  ) as Record<string, unknown>;
  const stub = await startFinoraStub({ finance: true, financeVouchers: [receipt] });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-installment-receipt-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-installment-receipt-e2e-")
  )
    throw Error("Unsafe test cleanup");
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const screenshots = path.join(artifacts, "erp-customers");
  mkdirSync(screenshots, { recursive: true });
  try {
    const page = await app.firstWindow();
    const login = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await login.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await login.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await login.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await login.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page.getByRole("dialog", { name: "المزيد" }).getByText("الحسابات", { exact: true }).click();
    const panel = page.getByRole("dialog", { name: "الحسابات", exact: true });
    await panel
      .getByRole("row")
      .filter({ hasText: String(receipt.number) })
      .click();
    const detail = panel.getByRole("complementary");
    await expect(detail.getByText("فاتورة بيع #1", { exact: true })).toBeVisible();
    await expect(detail.getByText("دفعة قسط #1", { exact: true })).toBeVisible();
    await expect(detail.getByText("دفعة قسط #2", { exact: true })).toBeVisible();
    await expect(detail).not.toContainText("credit_plan_payment");
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, size) => {
          const window = BrowserWindow.getAllWindows()[0];
          window?.setMinimumSize(900, 650);
          window?.setContentSize(size.width, size.height);
        },
        { width, height },
      );
      await detail
        .getByRole("heading", { name: "المستندات المرتبطة" })
        .getByRole("button", { name: "شرح الميزة" })
        .click();
      const note = page.getByRole("note").filter({ hasText: "حصص الأقساط جزء من سداد المستند" });
      await expect(note).toBeVisible();
      await expect(note).toBeInViewport({ ratio: 0.95 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(screenshots, `finance-installments-${width}.png`) });
      await page.keyboard.press("Escape");
      await expect(note).toBeHidden();
    }
    expect(stub.bodies.some((request) => request.path === "/api/finance/commands")).toBe(false);
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
