import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeTestProfile(profile: string) {
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-order-edit-e2e-")
  )
    throw new Error("Unsafe test cleanup");
  rmSync(profile, { recursive: true, force: true });
}

test("native order quick editing saves once and refreshes the order drawer and table", async () => {
  const appDir = path.resolve(__dirname, "..");
  const stub = await startFinoraStub({ orderEditing: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-order-edit-e2e-"));
  const app = await electron.launch({
    args: [appDir],
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
      .getByRole("button", { name: "الطلبات", exact: true })
      .click();
    await page.getByRole("button", { name: "إجراءات الطلب 10045" }).click();
    await page.getByRole("menuitem", { name: "عرض التفاصيل" }).click();
    const drawer = page.getByRole("complementary", { name: "الطلب #10045" });
    await drawer.getByRole("button", { name: "تعديل سريع", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "تعديل سريع للطلب #10045" });
    await editor.getByLabel("اسم الزبون", { exact: true }).fill("أحمد المعدّل");
    await editor.getByLabel("كمية شاشة LG", { exact: true }).fill("2");
    // Focus swaps formatted money for raw digits; replace it using the cashier's keyboard flow.
    const price = editor.getByLabel("سعر شاشة LG", { exact: true });
    await price.click();
    await expect(price).toHaveValue("450000");
    await price.press("Control+a");
    await price.pressSequentially("100000");
    await editor.getByLabel("خصم الطلب", { exact: true }).fill("5000");
    await editor.getByLabel("ملاحظات الطلب", { exact: true }).fill("التوصيل مساءً");
    await expect(editor.getByLabel("كمية شاشة LG", { exact: true })).toHaveValue("2");
    await expect(editor.getByLabel("سعر شاشة LG", { exact: true })).toHaveValue("100,000");
    await expect(editor.getByLabel("خصم الطلب", { exact: true })).toHaveValue("5,000");
    await expect(
      editor.getByText("الإجمالي بعد التعديل", { exact: true }).locator("..").locator("p").last(),
    ).toHaveText("195,000 د.ع");
    for (const width of [1536, 1180]) {
      await app.evaluate(
        ({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0]?.setContentSize(size, 850),
        width,
      );
      await expect(editor.getByRole("button", { name: "حفظ التعديلات", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(appDir, "test-results", `order-quick-edit-${width}.png`) });
    }
    await editor.press("Control+Enter");
    await expect(editor).not.toBeVisible();
    await expect(drawer.getByText("التوصيل مساءً", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("row").filter({ hasText: "أحمد المعدّل" }).getByText("195,000 د.ع", { exact: true }),
    ).toBeVisible();
    const edits = stub.bodies.filter((request) => request.path === "/orders/quick-edit/10045");
    expect(edits).toHaveLength(1);
    expect(edits[0]?.body).toMatchObject({
      items: [{ product_id: 1, qty: 2, price: 100000, color: "أسود", sale_mode: "normal" }],
      discount_amount: 5000,
    });
  } finally {
    await app.close();
    await stub.close();
    removeTestProfile(profile);
  }
});
