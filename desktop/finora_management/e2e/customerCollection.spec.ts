import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("customer invoice opens a prefilled financial collection and keeps the exact allocation through approval", async () => {
  const stub = await startFinoraStub({ customers: true, finance: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-customer-collection-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-customer-collection-e2e-")
  )
    throw Error("Unsafe test cleanup");
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const artifacts = path.resolve(__dirname, "../../../tests/_artifacts/erp-customers");
  mkdirSync(artifacts, { recursive: true });
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
    const customer = customers.getByRole("complementary", { name: "أحمد العميل", exact: true });
    await customer.getByRole("tab", { name: "كشف المستحقات", exact: true }).click();
    const invoice = customer.locator("article").filter({ hasText: "فاتورة #10" });
    await expect(customer.getByRole("button", { name: "تحصيل الفاتورة", exact: true })).toHaveCount(1);
    await invoice.getByRole("button", { name: "تحصيل الفاتورة", exact: true }).click();
    const finance = page.getByRole("dialog", { name: "الحسابات", exact: true });
    const editor = finance.getByRole("complementary", { name: "تحصيل فاتورة #10", exact: true });
    await expect(editor.getByText("أحمد العميل", { exact: true })).toBeVisible();
    await expect(editor.getByText("الفرع الرئيسي", { exact: true })).toBeVisible();
    await expect(editor.getByText("#10", { exact: true })).toBeVisible();
    await expect(editor.getByLabel("المبلغ بالدينار")).toHaveValue("200000");
    await expect(editor.getByLabel("طريقة الحفظ")).toHaveValue("draft");
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
      await expect(editor.getByRole("button", { name: "حفظ العملية", exact: true })).toBeInViewport();
      await expect(editor.getByLabel("المبلغ بالدينار")).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(artifacts, `collection-${width}.png`) });
    }
    expect(stub.bodies.filter((item) => item.path === "/api/finance/commands")).toHaveLength(0);
    await editor.getByLabel("المبلغ بالدينار").fill("100000");
    await editor.getByRole("button", { name: "حفظ العملية", exact: true }).click();
    const row = finance.getByRole("row").filter({ hasText: "أحمد العميل" });
    await expect(row.getByText("مسودة", { exact: true })).toBeVisible();
    const command = stub.bodies.find((item) => item.path === "/api/finance/commands")?.body;
    expect(command).toMatchObject({
      operation: "voucher.create",
      category: "customer_payment",
      party_id: "1",
      branch_id: "1",
      amount: "100000",
      intent: "draft",
      allocations: [{ invoice_id: 10, amount: 100000 }],
    });
    await row.click();
    const detail = finance.getByRole("complementary");
    await detail.getByRole("button", { name: "اعتماد وترحيل", exact: true }).click();
    const review = finance.getByRole("complementary", { name: /مراجعة العملية/ });
    await review.getByRole("button", { name: "تأكيد العملية", exact: true }).click();
    await expect(row.getByText("مرحّل", { exact: true })).toBeVisible();
    expect(stub.bodies.filter((item) => item.path === "/api/finance/commands")).toHaveLength(2);
    await finance.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
    await finance.getByRole("button", { name: "سند جديد", exact: true }).click();
    const unsaved = finance.getByRole("complementary", { name: "سند مالي جديد", exact: true });
    await unsaved.getByLabel("المبلغ بالدينار").fill("70000");
    await page.getByRole("button", { name: "العملاء", exact: true }).click();
    await customer.getByRole("tab", { name: "كشف المستحقات", exact: true }).click();
    await invoice.getByRole("button", { name: "تحصيل الفاتورة", exact: true }).click();
    await expect(unsaved.getByLabel("المبلغ بالدينار")).toHaveValue("70000");
    await expect(finance.getByText(/احفظ النموذج الحالي أو أغلقه/)).toBeVisible();
    await finance.getByRole("button", { name: "إلغاء الانتقال", exact: true }).click();
    await expect(unsaved.getByLabel("المبلغ بالدينار")).toHaveValue("70000");
    expect(stub.bodies.filter((item) => item.path === "/api/finance/commands")).toHaveLength(2);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
