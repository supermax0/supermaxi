import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("native supplier workbench: RTL layout, editing, payment, sale with colors and purchase", async () => {
  const stub = await startFinoraStub();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-suppliers-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-suppliers-e2e-")
  )
    throw new Error("Unexpected test profile path");
  const appDir = path.resolve(__dirname, "..");
  const app = await electron.launch({
    args: [appDir],
    cwd: appDir,
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  try {
    const page = await app.firstWindow();
    const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await form.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await form.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await form.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await form.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page.getByRole("dialog", { name: "المزيد" }).getByText("الموردين", { exact: true }).click();
    const workbench = page.getByRole("dialog", { name: "الموردين", exact: true });
    const table = workbench.getByRole("region", { name: "الموردين" }).getByRole("table");
    await expect(table.getByRole("row")).toHaveCount(9);
    await table
      .getByRole("row")
      .filter({ hasText: "شركة الأمل" })
      .getByRole("button", { name: "فتح", exact: true })
      .click();
    const details = page.getByRole("complementary", { name: "تفاصيل المورد" });
    await expect(details.getByRole("heading", { name: "شركة الأمل" })).toBeVisible();
    const dismissWelcome = page.getByRole("button", { name: "إخفاء", exact: true });
    if (await dismissWelcome.isVisible()) await dismissWelcome.click();
    await page.waitForTimeout(600);
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setContentSize(1536, 1000));
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(appDir, "test-results", "suppliers-desktop.png") });
    for (const [width, height] of [
      [1180, 700],
      [1920, 1080],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, size) =>
          BrowserWindow.getAllWindows()[0]?.setContentSize(size.width, size.height),
        { width, height },
      );
      await page.waitForTimeout(350);
      await expect(details.getByRole("button", { name: "تسجيل دفعة", exact: true })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(overflow).toBe(false);
      await page.screenshot({ path: path.join(appDir, "test-results", `suppliers-${width}.png`) });
    }
    await details.getByRole("tab", { name: "المشتريات", exact: true }).click();
    await expect(details.getByText("P-0048", { exact: true })).toBeVisible();
    await details.getByRole("tab", { name: "الدفعات", exact: true }).click();
    await expect(details.getByText("دفعة على الحساب", { exact: true })).toBeVisible();
    await details.getByRole("button", { name: "تعديل", exact: true }).click();
    const edit = page.getByRole("dialog", { name: "تعديل المورد", exact: true });
    await edit.getByLabel("العنوان", { exact: true }).fill("بغداد - المنصور");
    await edit.getByRole("button", { name: "حفظ المورد" }).click();
    await expect(edit).not.toBeVisible();
    await expect(details.getByText("بغداد - المنصور", { exact: true })).toBeVisible();
    await details.getByRole("button", { name: "تسجيل دفعة", exact: true }).click();
    const pay = page.getByRole("dialog", { name: "تسجيل دفعة للمورد", exact: true });
    await pay.getByRole("textbox", { name: "مبلغ الدفعة", exact: true }).fill("6000000");
    await expect(pay.getByRole("button", { name: "تأكيد الدفعة" })).toBeDisabled();
    await pay.getByRole("textbox", { name: "مبلغ الدفعة", exact: true }).fill("100000");
    await pay.getByRole("button", { name: "تأكيد الدفعة" }).click();
    await expect(pay).not.toBeVisible();
    await expect(details.getByText("5,100,000", { exact: true })).toBeVisible();
    expect(stub.bodies.find((b) => b.path === "/suppliers/api/3/pay")?.body).toMatchObject({
      amount: 100000,
      treasury_account_id: 1,
    });
    await page.keyboard.press("Escape");
    await expect(details).not.toBeVisible();
    await expect(workbench).toBeVisible();
    const search = workbench.getByRole("searchbox");
    await search.fill("07709876543");
    await expect(table.getByRole("row")).toHaveCount(2);
    await expect(table.getByText("شركة بغداد", { exact: true })).toBeVisible();
    await search.fill("");
    await workbench.getByRole("tab", { name: /لنا رصيد/ }).click();
    await expect(table.getByRole("row")).toHaveCount(3);
    await workbench.getByRole("tab", { name: /الكل/ }).click();
    await workbench.getByRole("button", { name: "إضافة مورد", exact: true }).click();
    const create = page.getByRole("dialog", { name: "إضافة مورد", exact: true });
    await create.getByLabel("اسم المورد", { exact: true }).fill("مورد جديد للتجربة");
    await create.getByLabel("الهاتف", { exact: true }).fill("07700001122");
    await create.getByLabel("الرصيد الافتتاحي", { exact: true }).fill("500000");
    await create.getByRole("button", { name: "حفظ المورد" }).click();
    await expect(create).not.toBeVisible();
    await expect(details.getByRole("heading", { name: "مورد جديد للتجربة" })).toBeVisible();
    await details.getByRole("tab", { name: "المبيعات للمورد", exact: true }).click();
    await details.getByRole("button", { name: "بيع للمورد", exact: true }).click();
    const sale = page.getByRole("dialog", { name: "بيع للمورد", exact: true });
    await expect(sale.getByRole("button", { name: "تسجيل البيع" })).toBeDisabled();
    await sale.getByRole("searchbox").fill("6290000000011");
    await sale.getByRole("button", { name: /شاشة LG 50/ }).click();
    await sale.getByLabel("كمية شاشة LG 50", { exact: true }).fill("9");
    await expect(sale.getByRole("button", { name: "تسجيل البيع" })).toBeDisabled();
    await sale.getByLabel("كمية شاشة LG 50", { exact: true }).fill("2");
    await sale.getByRole("searchbox").fill("سماعة");
    await sale.getByRole("button", { name: /سماعة ملونة/ }).click();
    await expect(sale.getByRole("button", { name: "تسجيل البيع" })).toBeDisabled();
    await sale.getByLabel("لون سماعة ملونة", { exact: true }).selectOption("أبيض");
    await expect(sale.getByText("رصيد لنا بعد البيع", { exact: true })).toBeVisible();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setContentSize(1180, 700));
    await sale.getByRole("button", { name: "تسجيل البيع" }).scrollIntoViewIfNeeded();
    await expect(sale.getByRole("button", { name: "تسجيل البيع" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
    await page.screenshot({ path: path.join(appDir, "test-results", "suppliers-sale-1180.png") });
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setContentSize(1536, 1000));
    await page.screenshot({ path: path.join(appDir, "test-results", "suppliers-sale-dialog.png") });
    await sale.getByRole("button", { name: "تسجيل البيع" }).click();
    await expect(sale).not.toBeVisible();
    await expect(details.getByText("SS-20261009-0001", { exact: true })).toBeVisible();
    expect(stub.bodies.find((b) => b.path === "/api/v1/desktop/sync/supplier-sale")?.body).toMatchObject({
      items: [
        { product_id: 201, qty: 2, price: 325000 },
        { product_id: 202, qty: 1, price: 55000, variant_color: "أبيض" },
      ],
    });
    await page.screenshot({ path: path.join(appDir, "test-results", "suppliers-sale.png") });
    await details.getByRole("button", { name: "إضافة فاتورة شراء" }).click();
    await expect(page.getByRole("dialog", { name: "فاتورة شراء جديدة" })).toBeVisible();
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
