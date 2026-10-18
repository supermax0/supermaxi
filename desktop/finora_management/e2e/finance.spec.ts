import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("finance uses the existing RTL workbench, help and side panels through draft and approval", async () => {
  test.setTimeout(180000);
  const stub = await startFinoraStub({ finance: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-finance-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-finance-e2e-")
  )
    throw Error("Unsafe test cleanup");
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const login = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await login.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await login.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await login.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await login.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page.getByRole("dialog", { name: "المزيد" }).getByText("الحسابات", { exact: true }).click();
    const panel = page.getByRole("dialog", { name: "الحسابات", exact: true });
    await expect(panel.getByRole("tab", { name: "القبض والصرف" })).toHaveAttribute("aria-selected", "true");
    await expect(panel.getByText("لا توجد سندات", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "شرح الميزة", exact: true }).first().click();
    await expect(page.getByRole("note").filter({ hasText: "السند المسودة" })).toBeVisible();
    await page.keyboard.press("Escape");
    await panel.getByRole("button", { name: "سند جديد", exact: true }).click();
    const editor = panel.getByRole("complementary", { name: "سند مالي جديد" });
    await editor.getByLabel("الجهة / عنوان المصروف").fill("كهرباء الفرع");
    await editor.getByLabel("المبلغ بالدينار").fill("200000");
    await expect(editor.getByLabel("طريقة الحفظ")).toHaveValue("draft");
    await page.screenshot({ path: "test-results/finance-draft-editor.png" });
    await editor.getByRole("button", { name: "حفظ العملية", exact: true }).click();
    await expect(panel.getByRole("row").filter({ hasText: "كهرباء الفرع" })).toBeVisible();
    const row = panel.getByRole("row").filter({ hasText: "كهرباء الفرع" });
    await row.click();
    const detail = panel.getByRole("complementary");
    await expect(detail.getByText("مسودة", { exact: true })).toBeVisible();
    await detail.getByRole("button", { name: "تعديل المسودة", exact: true }).click();
    const edit = panel.getByRole("complementary", { name: "تعديل المسودة" });
    await expect(edit.getByLabel("المبلغ بالدينار")).toHaveValue("200000");
    await edit.getByLabel("المبلغ بالدينار").fill("210000");
    await edit.getByRole("button", { name: "حفظ العملية", exact: true }).click();
    await row.click();
    await expect(detail.getByText("210,000", { exact: false }).first()).toBeVisible();
    await detail.getByRole("button", { name: "اعتماد وترحيل", exact: true }).click();
    const review = panel.getByRole("complementary", { name: /مراجعة العملية/ });
    await review.getByRole("button", { name: "تأكيد العملية", exact: true }).click();
    await expect(
      panel.getByRole("row").filter({ hasText: "كهرباء الفرع" }).getByText("مرحّل", { exact: true }),
    ).toBeVisible();
    await page.screenshot({ path: "test-results/finance-posted-details.png" });
    await panel.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
    await panel.getByRole("button", { name: "سند جديد", exact: true }).click();
    await editor.getByLabel("سبب العملية").selectOption("customer_payment");
    await editor.getByLabel("الجهة", { exact: true }).selectOption("3");
    await editor.getByLabel("المبلغ بالدينار").fill("150000");
    await editor.getByRole("button", { name: "حفظ العملية", exact: true }).click();
    await panel.getByRole("row").filter({ hasText: "تسديد زبون" }).click();
    await detail.getByRole("button", { name: "كشف حساب الجهة", exact: true }).click();
    const statement = panel.getByRole("complementary", { name: "كشف حساب زبون تجربة" });
    await expect(panel.getByRole("complementary")).toHaveCount(1);
    await expect(statement.getByText("250,000", { exact: false }).first()).toBeVisible();
    await expect(statement.getByText("فاتورة بيع #10", { exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/finance-party-statement.png" });
    await statement.getByRole("button").filter({ hasText: "PY-000002" }).click();
    await expect(detail.getByText("تسديد زبون", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
    await panel.getByRole("tab", { name: "الصناديق والحسابات" }).click();
    await expect(panel.getByRole("row").filter({ hasText: "حساب المصرف" })).toBeVisible();
    await panel.getByRole("tab", { name: "السلف والقروض" }).click();
    await expect(panel.getByText("لا توجد عقود", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "عقد جديد", exact: true }).click();
    const loan = panel.getByRole("complementary", { name: "عقد سلفة أو قرض" });
    await loan.getByLabel("أصل القرض / السلفة").fill("6000000");
    await expect(loan.getByText("صافي التمويل:", { exact: false })).toContainText("6,000,000");
    await page.screenshot({ path: "test-results/finance-loan-editor.png" });
    await loan.getByRole("button", { name: "إغلاق", exact: true }).click();
    await panel.getByRole("tab", { name: "القيود والتقارير" }).click();
    await panel.getByLabel("التقرير المحاسبي").selectOption("customer-aging");
    await expect(panel.getByRole("row").filter({ hasText: "زبون تقرير" })).toBeVisible();
    await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0];
      window?.setMinimumSize(900, 650);
      window?.setSize(1024, 768);
    });
    await expect(panel.getByRole("row").filter({ hasText: "زبون تقرير" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({ path: "test-results/finance-report-1024.png" });
    expect(errors).toEqual([]);
    const bodies = stub.bodies.filter((b) => b.path === "/api/finance/commands");
    expect(bodies[0]?.body).toMatchObject({ operation: "voucher.create", intent: "draft", amount: "200000" });
    expect(bodies[1]?.body).toMatchObject({ operation: "voucher.edit", amount: "210000", id: 1, version: 1 });
    expect(bodies[2]?.body).toMatchObject({ operation: "voucher.approve", version: 2 });
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
