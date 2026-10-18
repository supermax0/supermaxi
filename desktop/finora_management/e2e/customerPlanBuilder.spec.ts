import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

for (const history of ["unpaid", "direct", "voucher", "reversed"] as const)
  test(`customer schedules ${history} invoice and repartitions future rows without losing payment identities`, async () => {
    const priorPayments = history !== "unpaid";
    const financialHistory = history === "voucher" || history === "reversed";
    const historicalPaid = history === "reversed" ? 0 : 30000;
    test.setTimeout(120000);
    const stub = await startFinoraStub({
      customers: true,
      customerPlanBuilder: true,
      customerPriorPayments: priorPayments,
      customerVoucherHistory: financialHistory,
      customerReversedHistory: history === "reversed",
      finance: financialHistory,
      financeVouchers: financialHistory
        ? [
            {
              id: 6,
              number: "RC-000006",
              kind: "receipt",
              category: "customer_payment",
              category_label: "تحصيل دين عميل",
              party_type: "customer",
              party_id: 1,
              party_name: "أحمد العميل",
              amount: 30000,
              account_name: "حساب المصرف",
              treasury_account_id: 2,
              target_account_id: null,
              branch_id: 1,
              transaction_date: "2026-10-03",
              status: history === "reversed" ? "reversed" : "posted",
              version: history === "reversed" ? 2 : 1,
              notes: "تحصيل قبل الجدولة",
              source_type: null,
              source_id: null,
              reversal_id: history === "reversed" ? 7 : null,
              allocations: [],
              audit: [],
              attachments: [],
              journal: [],
              payload: {},
            },
          ]
        : undefined,
    });
    const profile = mkdtempSync(path.join(tmpdir(), "finora-plan-builder-e2e-"));
    if (
      path.dirname(profile) !== path.resolve(tmpdir()) ||
      !path.basename(profile).startsWith("finora-plan-builder-e2e-")
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
      await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
      await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
      await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
      await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
      await page.getByRole("button", { name: "العملاء", exact: true }).click();
      const customers = page.getByRole("dialog", { name: "العملاء", exact: true });
      await customers.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
      const details = customers.getByRole("complementary", { name: "أحمد العميل" });
      await details
        .locator("article")
        .filter({ hasText: "فاتورة #10" })
        .getByRole("button", { name: "إنشاء جدول أقساط", exact: true })
        .click();
      const create = page.getByRole("dialog", { name: "إنشاء جدول أقساط", exact: true });
      await expect(create.getByRole("alert")).toContainText("الفاتورة مرتبطة بجدول");
      await expect(create.getByRole("button", { name: "حفظ تقسيم الأقساط" })).toBeDisabled();
      await create.getByRole("button", { name: "إغلاق تقسيم الأقساط" }).click();
      await details
        .locator("article")
        .filter({ hasText: "فاتورة #11" })
        .getByRole("button", { name: "إنشاء جدول أقساط", exact: true })
        .click();
      await create.getByLabel("أول استحقاق جديد").fill("2027-01-31");
      await create.getByLabel("سبب تقسيم الأقساط").fill("طلب العميل إنشاء جدول شهري");
      if (priorPayments) {
        await expect(create.getByRole("row").filter({ hasText: "محفوظ — تحصيل سابق" })).toContainText(
          history === "reversed" ? "0 د.ع" : "30,000",
        );
        await expect(create.getByText("المبلغ القابل للتقسيم").locator("..")).toContainText(
          history === "reversed" ? "90,000" : "60,000",
        );
        await expect(create.getByLabel("عدد الأقساط المتاحة")).toHaveAttribute("max", "239");
      }
      if (financialHistory) {
        const sources = create.getByRole("region", { name: "سندات التحصيل السابقة" });
        await expect(sources).toContainText("RC-000006");
        await expect(sources).toContainText("حصة هذه الفاتورة");
        await expect(sources).toContainText("30,000");
        await expect(sources).toContainText(history === "reversed" ? "معكوس" : "مرحّل");
      }
      await expect(create.getByRole("cell", { name: "2027-02-28", exact: true })).toBeVisible();
      await expect(create.getByRole("cell", { name: "2027-03-31", exact: true })).toBeVisible();
      await create.getByRole("button", { name: "شرح تقسيم الأقساط" }).click();
      await expect(page.getByRole("note")).toContainText("لا تنشئ بيعاً أو قبضاً جديداً");
      await page.keyboard.press("Escape");
      await expect(create).toBeVisible();
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
        await expect
          .poll(async () => {
            const box = await create.boundingBox(),
              view = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
            return (
              !!box &&
              box.x >= 0 &&
              box.y >= 0 &&
              box.x + box.width <= view.width + 1 &&
              box.y + box.height <= view.height + 1
            );
          })
          .toBe(true);
        expect(
          (await create.getByRole("region", { name: "معاينة تقسيم الأقساط" }).boundingBox())?.height ?? 0,
        ).toBeGreaterThanOrEqual(200);
        await page.screenshot({
          path: path.join(
            artifacts,
            `${history === "reversed" ? "reversed-history" : history === "voucher" ? "voucher-history" : priorPayments ? "prior-payments" : "plan-builder"}-${width}.png`,
          ),
        });
      }
      await create.getByRole("button", { name: "حفظ تقسيم الأقساط" }).click();
      const created = page.getByRole("dialog", { name: "جدولة الأقساط #4", exact: true });
      await expect(created.getByLabel("قيمة القسط 1")).toHaveValue(history === "reversed" ? "" : "30,000");
      if (priorPayments) {
        await expect(created.getByLabel("قيمة القسط 1")).toBeDisabled();
        await expect(created.getByLabel("قيمة القسط 2")).toHaveValue(historicalPaid ? "20,000" : "30,000");
        await expect(created.getByLabel("قيمة القسط 4")).toHaveValue(historicalPaid ? "20,000" : "30,000");
      }
      await created.getByText("تاريخ تعديل الجدولة (1)", { exact: true }).click();
      await expect(created.getByText("طلب العميل إنشاء جدول شهري", { exact: true })).toBeVisible();
      await expect(created.getByText("قسط جديد #1", { exact: false })).toBeVisible();
      if (history === "reversed") {
        await expect(created.getByLabel("استحقاق القسط 1")).toBeDisabled();
        await created.getByLabel("استحقاق القسط 2").fill("2027-04-01");
        await created.getByLabel("سبب إعادة الجدولة").fill("تأجيل المستقبل مع حفظ تاريخ العكس");
        await created.getByRole("button", { name: "حفظ الجدولة" }).click();
        await expect(created.getByText("تاريخ تعديل الجدولة (2)", { exact: true })).toBeVisible();
        await expect(created.getByLabel("استحقاق القسط 1")).toHaveValue("2026-10-01");
        const edit = stub.bodies.find((row) => row.path.endsWith("/plans/4/schedule"));
        expect(edit?.body).toMatchObject({
          installments: [
            { id: 19, date: "2026-10-01", total: 0 },
            { id: 20, date: "2027-04-01", total: 30000 },
            { id: 21, date: "2027-02-28", total: 30000 },
            { id: 22, date: "2027-03-31", total: 30000 },
          ],
        });
      }
      await created.getByRole("button", { name: "إغلاق الجدولة" }).click();
      await details.getByRole("tab", { name: "الأقساط", exact: true }).click();
      await details.getByRole("button", { name: "جدولة الخطة 1", exact: true }).click();
      const original = page.getByRole("dialog", { name: "جدولة الأقساط #1", exact: true });
      await original.getByRole("button", { name: "تغيير عدد الأقساط المتاحة" }).click();
      const repartition = page.getByRole("dialog", { name: "تقسيم الأقساط المتاحة", exact: true });
      await repartition.getByLabel("أول استحقاق جديد").fill("2027-01-31");
      await repartition.getByLabel("سبب تقسيم الأقساط").fill("طلب العميل تقسيم الأقساط غير المسددة");
      await expect(repartition.getByRole("row")).toHaveCount(6);
      await expect(repartition.getByRole("cell", { name: "محفوظ — مرتبط بدفعات", exact: true })).toHaveCount(
        2,
      );
      await repartition.getByRole("button", { name: "حفظ تقسيم الأقساط" }).click();
      await expect(original.getByLabel("قيمة القسط 1")).toHaveValue("75,000");
      await expect(original.getByLabel("قيمة القسط 2")).toBeDisabled();
      await expect(original.getByLabel("قيمة القسط 3")).toHaveValue("50,000");
      await expect(original.getByLabel("قيمة القسط 5")).toHaveValue("50,000");
      const commands = stub.bodies.filter(
        (row) => row.path.endsWith("/repartition") || row.path.endsWith("/invoices/11/schedule"),
      );
      expect(commands).toHaveLength(2);
      expect(commands[0]?.body).toMatchObject({
        count: 3,
        first_due_date: "2027-01-31",
        interval: "monthly",
      });
      expect(commands[1]?.body).toMatchObject({
        count: 3,
        first_due_date: "2027-01-31",
        interval: "monthly",
      });
      expect(
        stub.bodies.filter((row) => row.path.startsWith("/api/finance") || row.path.startsWith("/orders")),
      ).toHaveLength(0);
      if (financialHistory) {
        await original.getByRole("button", { name: "إغلاق الجدولة" }).click();
        await details.getByRole("tab", { name: "الفواتير", exact: true }).click();
        await details
          .locator("article")
          .filter({ hasText: "فاتورة #11" })
          .getByRole("button", { name: "إنشاء جدول أقساط", exact: true })
          .click();
        await create.getByRole("button", { name: "فتح السند RC-000006" }).click();
        const accounts = page.getByRole("dialog", { name: "الحسابات", exact: true });
        await expect(accounts.getByRole("complementary", { name: "RC-000006", exact: true })).toBeVisible();
        await expect(accounts.getByRole("complementary", { name: "سند مالي جديد", exact: true })).toHaveCount(
          0,
        );
        expect(stub.bodies.filter((row) => row.path.startsWith("/api/finance"))).toHaveLength(0);
      }
      expect(errors).toEqual([]);
    } catch (error) {
      await cleanup();
      throw error;
    }
    await cleanup();
  });
