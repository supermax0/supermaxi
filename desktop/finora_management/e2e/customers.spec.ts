import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("customers opens through real IPC, filters, pages and preserves full table size beside details", async () => {
  test.setTimeout(120000);
  const stub = await startFinoraStub({ customers: true, orderEditing: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-customers-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-customers-e2e-")
  )
    throw Error("Unsafe cleanup");
  const artifacts = path.resolve(__dirname, "../../../tests/_artifacts/erp-customers");
  mkdirSync(artifacts, { recursive: true });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
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
    await page.getByRole("button", { name: "العملاء", exact: true }).click();
    const panel = page.getByRole("dialog", { name: "العملاء", exact: true });
    const table = panel.getByRole("region", { name: "جدول العملاء" });
    await expect(panel.getByRole("row").filter({ hasText: "أحمد العميل" })).toBeVisible();
    await panel.getByRole("button", { name: "إضافة عميل", exact: true }).click();
    const editor = panel.getByRole("complementary", { name: "إضافة عميل", exact: true });
    await editor.getByLabel("اسم العميل").fill("عميل جديد للاختبار");
    await editor.getByLabel(/^رقم الهاتف/).fill("07712345678");
    await editor.getByRole("button", { name: "حفظ العميل", exact: true }).click();
    const created = panel.getByRole("complementary", { name: "عميل جديد للاختبار", exact: true });
    await expect(created).toBeVisible();
    await created.getByRole("button", { name: "تعديل ملف العميل", exact: true }).click();
    const edit = panel.getByRole("complementary", { name: "تعديل ملف العميل", exact: true });
    await expect(edit.getByLabel("اسم العميل")).toHaveValue("عميل جديد للاختبار");
    await edit.getByLabel("اسم العميل").fill("عميل معدل للاختبار");
    await edit.getByRole("button", { name: "حفظ العميل", exact: true }).click();
    const updated = panel.getByRole("complementary", { name: "عميل معدل للاختبار", exact: true });
    await expect(updated).toBeVisible();
    await updated.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
    await panel.getByRole("tab", { name: "أقساط متأخرة", exact: true }).click();
    await expect(panel.getByRole("row")).toHaveCount(2);
    await panel.getByRole("tab", { name: "كل العملاء", exact: true }).click();
    await panel.getByRole("button", { name: "الصفحة التالية", exact: true }).click();
    await expect(panel.getByRole("row").filter({ hasText: "عميل 31" })).toBeVisible();
    await panel.getByRole("button", { name: "الصفحة السابقة", exact: true }).click();
    await panel.getByRole("searchbox").fill("أحمد");
    await expect(panel.getByRole("row")).toHaveCount(2);
    await panel.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
    const details = panel.getByRole("complementary", { name: "أحمد العميل" });
    await expect(details.getByText("فاتورة #10", { exact: true })).toBeVisible();
    await details.getByRole("tab", { name: "الأقساط", exact: true }).click();
    await expect(details.getByText("متأخر", { exact: true })).toBeVisible();
    await expect(details.getByText("50,000 د.ع", { exact: true }).last()).toBeVisible();
    await details.getByRole("tab", { name: "كشف المستحقات", exact: true }).click();
    await expect(details.getByText("رصيد افتتاحي", { exact: true })).toBeVisible();
    await expect(details.getByText("350,000 د.ع", { exact: true })).toBeVisible();
    await expect(details.getByText("200,000 د.ع", { exact: true })).toBeVisible();
    await expect(details.locator("article")).toHaveCount(2);
    await expect(details.getByRole("button", { name: "تحصيل الفاتورة", exact: true })).toHaveCount(0);
    await details.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, dimensions) => {
          const window = BrowserWindow.getAllWindows()[0];
          window?.setMinimumSize(900, 650);
          window?.setSize(dimensions.width, dimensions.height);
        },
        { width, height },
      );
      await expect(table).toBeVisible();
      await expect.poll(async () => (await table.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(260);
      const bounds = await table.boundingBox();
      expect(bounds?.height ?? 0).toBeGreaterThanOrEqual(260);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await page.screenshot({ path: path.join(artifacts, `${width}-list.png`) });
      await panel.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
      await expect(details).toBeVisible();
      await expect.poll(() => details.evaluate((element) => getComputedStyle(element).opacity)).toBe("1");
      await expect(details.getByText("فاتورة #10", { exact: true })).toBeVisible();
      expect((await table.boundingBox())?.width).toBe(bounds?.width);
      await page.screenshot({ path: path.join(artifacts, `${width}-details.png`) });
      await details.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
      await expect(details).toHaveCount(0);
    }
    expect(errors).toEqual([]);
    await panel.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
    await details.getByRole("button", { name: "فتح الفاتورة الأصلية", exact: true }).click();
    const ordersPanel = page.getByRole("dialog", { name: "إدارة الطلبات", exact: true });
    const orderDetail = ordersPanel.getByRole("complementary", { name: "الطلب #10", exact: true });
    await expect(orderDetail.getByText("أحمد العميل", { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
    const commands = stub.bodies.filter((row) => row.path === "/api/v1/desktop/customers/commands");
    expect(commands).toHaveLength(2);
    expect(commands[0]?.body).toMatchObject({ operation: "create", data: { name: "عميل جديد للاختبار" } });
    expect(commands[1]?.body).toMatchObject({
      operation: "update",
      id: 32,
      revision: "b".repeat(64),
      data: { name: "عميل معدل للاختبار" },
    });
    expect(stub.requests.some((request) => request.includes("/api/v1/desktop/customers"))).toBe(true);
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
