import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test, type ElectronApplication } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

for (const mode of ["opening", "manual"] as const) {
  test(`${mode} customer save survives lost server response and Electron restart without a second operation`, async () => {
    test.setTimeout(120000);
    const stub = await startFinoraStub({
      customers: true,
      finance: true,
      customerDebtBuilder: true,
      dropFirstCustomerSaveResponse: true,
    });
    const profile = mkdtempSync(path.join(tmpdir(), "finora-customer-recovery-e2e-"));
    if (
      path.dirname(profile) !== path.resolve(tmpdir()) ||
      !path.basename(profile).startsWith("finora-customer-recovery-e2e-")
    )
      throw Error("Unsafe cleanup");
    const artifacts = path.resolve(__dirname, "../../../tests/_artifacts/erp-customers");
    mkdirSync(artifacts, { recursive: true });
    let app: ElectronApplication | null = null;
    const launch = () =>
      electron.launch({
        args: [path.resolve(__dirname, "..")],
        cwd: path.resolve(__dirname, ".."),
        env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
      });
    const errors: string[] = [];
    try {
      app = await launch();
      let page = await app.firstWindow();
      page.on("pageerror", (e) => errors.push(e.message));
      await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
      await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
      await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
      await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
      await page.getByRole("button", { name: "العملاء", exact: true }).click();
      let customers = page.getByRole("dialog", { name: "العملاء", exact: true });
      await customers.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
      const detail = customers.getByRole("complementary", { name: "أحمد العميل", exact: true });
      const reason = "طلب محفوظ بعد فقدان الرد";
      if (mode === "opening") {
        await detail.getByRole("button", { name: "تسجيل دين افتتاحي", exact: true }).click();
        const form = page.getByRole("dialog", { name: "تسجيل دين افتتاحي", exact: true });
        const amount = form.getByLabel("مبلغ الدين الافتتاحي");
        await amount.click();
        await amount.press("Control+a");
        await amount.pressSequentially("90000");
        await form.getByLabel("مرجع مصدر الدين").fill("EXT-RECOVER-001");
        await form.getByLabel("وصف الدين الافتتاحي").fill(reason);
        await form.getByLabel("أول استحقاق جديد").fill("2027-01-31");
        await form.getByRole("button", { name: "تسجيل الدين وترحيله", exact: true }).click();
      } else {
        await detail.getByRole("tab", { name: "الأقساط", exact: true }).click();
        await detail.getByRole("button", { name: "جدولة الخطة 1", exact: true }).first().click();
        const form = page.getByRole("dialog", { name: "جدولة الأقساط #1", exact: true });
        await form.getByLabel("استحقاق القسط 3").fill("2027-04-01");
        await form.getByLabel("سبب إعادة الجدولة").fill(reason);
        await form.getByRole("button", { name: "حفظ الجدولة", exact: true }).click();
      }
      await expect(
        page.getByText(
          "نتيجة الحفظ غير مؤكدة؛ أعد نفس الحفظ. بعد إعادة تشغيل البرنامج راجع طلبات الحفظ المحفوظة في صفحة العملاء.",
        ),
      ).toBeVisible({ timeout: 30000 });
      const original = stub.bodies.find(
        (r) =>
          r.path.startsWith("/api/v1/desktop/customers/") &&
          r.path.endsWith(mode === "opening" ? "/debts" : "/schedule"),
      );
      expect(original).toBeTruthy();
      const bytes = readFileSync(path.join(profile, "offline", "business.sqlite.enc"));
      expect(bytes.includes(Buffer.from(reason))).toBe(false);
      expect(bytes.includes(Buffer.from(JSON.stringify(original?.body)))).toBe(false);
      await app.close();
      app = null;
      app = await launch();
      page = await app.firstWindow();
      page.on("pageerror", (e) => errors.push(e.message));
      await page.getByRole("button", { name: "العملاء", exact: true }).click();
      customers = page.getByRole("dialog", { name: "العملاء", exact: true });
      await customers.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
      await expect(customers.getByRole("complementary", { name: "أحمد العميل", exact: true })).toBeVisible();
      await customers.getByRole("button", { name: "طلبات الحفظ المحفوظة", exact: true }).click();
      const recovery = customers.getByRole("complementary", { name: "طلبات الحفظ المحفوظة", exact: true });
      await expect(recovery).toContainText(reason);
      const retry = recovery.getByRole("button", { name: "تأكيد نفس الطلب", exact: true });
      if (mode === "opening") await expect(recovery).toContainText("EXT-RECOVER-001");
      else await expect(recovery.getByRole("cell", { name: "2027-04-01", exact: true })).toBeVisible();
      for (const [width, height] of [
        [1536, 900],
        [1180, 700],
        [1024, 768],
      ] as const) {
        await app.evaluate(
          ({ BrowserWindow }, size) => {
            const w = BrowserWindow.getAllWindows()[0];
            w?.setMinimumSize(900, 650);
            w?.setContentSize(size.width, size.height);
          },
          { width, height },
        );
        await expect(retry).toBeInViewport({ ratio: 1 });
        const review =
          mode === "opening"
            ? recovery.getByText(/90,000/)
            : recovery.getByRole("cell", { name: "2027-04-01", exact: true });
        await review.scrollIntoViewIfNeeded();
        await expect(review).toBeInViewport({ ratio: 1 });
        await expect
          .poll(async () => Number(await recovery.evaluate((el) => getComputedStyle(el).opacity)))
          .toBe(1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
        await page.screenshot({ path: path.join(artifacts, `recovery-${mode}-${width}.png`) });
      }
      expect(stub.bodies.filter((r) => r.path === original?.path)).toHaveLength(1);
      await retry.click();
      await expect(recovery).not.toBeVisible();
      await expect(customers.getByRole("button", { name: "طلبات الحفظ المحفوظة", exact: true })).toHaveCount(
        0,
      );
      const writes = stub.bodies.filter((r) => r.path === original?.path);
      expect(writes).toHaveLength(2);
      expect(writes[1]?.body).toEqual(original?.body);
      await expect(customers.getByRole("complementary", { name: "أحمد العميل", exact: true })).toBeVisible();
      await page.reload();
      await page.getByRole("button", { name: "العملاء", exact: true }).click();
      await expect(page.getByRole("button", { name: "طلبات الحفظ المحفوظة", exact: true })).toHaveCount(0);
      expect(stub.bodies.filter((r) => r.path === original?.path)).toHaveLength(2);
      expect(
        stub.bodies.filter(
          (r) => r.path === "/api/finance/commands" || r.path.startsWith("/orders/commands"),
        ),
      ).toHaveLength(0);
      expect(errors).toEqual([]);
    } finally {
      await app?.close();
      await stub.close();
      rmSync(profile, { recursive: true, force: true });
    }
  });
}
