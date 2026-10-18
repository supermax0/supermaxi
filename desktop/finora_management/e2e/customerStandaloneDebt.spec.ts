import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("standalone debt opens its exact collection and prior opening requires an explicit debt-only review", async () => {
  const stub = await startFinoraStub({ customers: true, finance: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-standalone-debt-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-standalone-debt-e2e-")
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
    await customer.getByRole("button", { name: "تحصيل الدين", exact: true }).click();
    const finance = page.getByRole("dialog", { name: "الحسابات", exact: true });
    const editor = finance.getByRole("complementary", { name: "تحصيل دين مستقل #2", exact: true });
    await expect(editor.getByLabel("المبلغ بالدينار")).toHaveValue("50000");
    await expect(editor.getByText("الدين المستهدف", { exact: true })).toBeVisible();
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
      await expect(editor.getByLabel("المبلغ بالدينار")).toBeInViewport();
      await expect(editor.getByRole("button", { name: "حفظ العملية", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(artifacts, `standalone-collection-${width}.png`) });
    }
    expect(stub.bodies.filter((item) => item.path === "/api/finance/commands")).toHaveLength(0);
    await editor.getByLabel("المبلغ بالدينار").fill("25000");
    await editor.getByRole("button", { name: "حفظ العملية", exact: true }).click();
    expect(stub.bodies.find((item) => item.path === "/api/finance/commands")?.body).toMatchObject({
      operation: "voucher.create",
      party_id: "1",
      category: "customer_payment",
      amount: "25000",
      allocations: [{ plan_id: 2, amount: 25000 }],
      intent: "draft",
    });
    await finance.getByRole("button", { name: "إعدادات الحسابات", exact: true }).click();
    const settings = finance.getByRole("complementary", { name: "إعدادات الحسابات", exact: true });
    const approve = settings.getByRole("button", { name: "اعتماد الديون المستقلة المعروضة", exact: true });
    await expect(approve).toBeVisible();
    await expect(settings.getByText("اعتماد الديون المستقلة السابقة", { exact: true })).toBeVisible();
    expect(stub.bodies.filter((item) => item.path === "/api/finance/commands")).toHaveLength(1);
    await approve.click();
    await expect(settings).not.toBeVisible();
    expect(stub.bodies.filter((item) => item.path === "/api/finance/commands")[1]?.body).toMatchObject({
      operation: "migration.apply",
      preview_hash: "reviewed-debts",
      reason: "اعتماد الديون المستقلة بعد مراجعة الفروقات",
    });
    await finance.getByRole("button", { name: "إعدادات الحسابات", exact: true }).click();
    await expect(settings.getByText("تم اعتماد الأرصدة الافتتاحية", { exact: true })).toBeVisible();
    await expect(approve).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
