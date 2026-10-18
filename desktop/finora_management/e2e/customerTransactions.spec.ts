import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

for (const [sample, printedRows] of [
  ["real", 6],
  ["many-real", 32],
] as const)
  test(`customer collections paginate, export, print real HTML and open original sources through IPC (${sample})`, async () => {
    test.setTimeout(150000);
    const outputs = path.resolve(__dirname, "../../../tests/_artifacts/erp-customers");
    mkdirSync(outputs, { recursive: true });
    const profile = mkdtempSync(path.join(tmpdir(), "finora-transactions-e2e-"));
    if (
      path.dirname(profile) !== path.resolve(tmpdir()) ||
      !path.basename(profile).startsWith("finora-transactions-e2e-")
    )
      throw Error("Unsafe cleanup");
    const stub = await startFinoraStub({
      customers: true,
      orderEditing: true,
      finance: true,
      customerTransactionsHtml: readFileSync(path.join(outputs, `transactions-${sample}.html`), "utf8"),
      financeVouchers: [
        {
          id: 1,
          number: "ST-000001",
          kind: "settlement",
          category: "customer_credit_apply",
          category_label: "تسوية رصيد مقدم",
          party_type: "customer",
          party_id: 1,
          party_name: "أحمد العميل",
          amount: 25000,
          account_name: "—",
          treasury_account_id: null,
          target_account_id: null,
          branch_id: 1,
          transaction_date: "2026-10-11",
          status: "posted",
          version: 1,
          notes: "سند مصدر التحصيل",
          source_type: null,
          source_id: null,
          reversal_id: null,
          allocations: [],
          audit: [],
          attachments: [],
          journal: [],
          payload: {},
        },
      ],
    });
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
      const openHistory = async () => {
        await page.getByRole("button", { name: "العملاء", exact: true }).click();
        const panel = page.getByRole("dialog", { name: "العملاء", exact: true });
        const details = panel.getByRole("complementary", { name: "أحمد العميل" });
        if (!(await details.isVisible()))
          await panel.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
        await details.getByRole("button", { name: "حركات التحصيل والتسويات", exact: true }).click();
      };
      await openHistory();
      const dialog = page.getByRole("dialog", { name: "حركات التحصيل — أحمد العميل", exact: true });
      const table = dialog.getByRole("region", { name: "جدول حركات التحصيل" });
      await expect(dialog.getByRole("row")).toHaveCount(26);
      await expect(dialog.getByRole("alert")).toContainText("لا تمثل حركة قبض جديدة");
      const settlement = dialog.getByRole("row").filter({ hasText: "تسوية رصيد مقدم" });
      await expect(settlement.locator("td").nth(3)).toHaveText("0 د.ع");
      await dialog.getByRole("button", { name: "شرح حركات التحصيل" }).click();
      await expect(page.getByRole("note").filter({ hasText: "السند يظهر مرة واحدة" })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toBeVisible();
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
        await expect(table).toBeVisible();
        await expect
          .poll(async () => {
            const box = await dialog.boundingBox();
            const viewport = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
            return (
              !!box &&
              box.x >= 0 &&
              box.y >= 0 &&
              box.x + box.width <= viewport.width + 1 &&
              box.y + box.height <= viewport.height + 1
            );
          })
          .toBe(true);
        expect((await table.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(200);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
        await page.screenshot({ path: path.join(outputs, `transactions-${width}.png`) });
      }
      await dialog.getByRole("button", { name: "الصفحة التالية" }).click();
      await expect(dialog.getByRole("row")).toHaveCount(8);
      await dialog.getByRole("button", { name: "الصفحة السابقة" }).click();
      const exported = path.join(profile, "customer-collections.csv");
      await app.evaluate(({ BrowserWindow }, destination) => {
        BrowserWindow.getAllWindows()[0]?.webContents.session.once("will-download", (_event, item) =>
          item.setSavePath(destination),
        );
      }, exported);
      await dialog.getByRole("button", { name: "تصدير كل الحركات" }).click();
      await expect.poll(() => existsSync(exported)).toBe(true);
      expect(readFileSync(exported, "utf8")).toContain("تحصيل دين");
      const next = app.waitForEvent("window");
      await dialog.getByRole("button", { name: "طباعة الحركات / PDF" }).click();
      const preview = await next;
      await expect(
        preview.getByRole("heading", { name: "حركات التحصيل والتسويات", exact: true }),
      ).toBeVisible();
      await expect(preview.getByRole("table").locator("tbody tr")).toHaveCount(printedRows);
      expect(preview.url()).toBe(`${stub.url}/api/v1/desktop/customers/1/transactions/print`);
      const data = await app.evaluate(async ({ BrowserWindow }) => {
        const win = BrowserWindow.getAllWindows().find((window) =>
          window.webContents.getURL().includes("/transactions/print"),
        );
        if (!win) throw Error("Collection print preview missing");
        return (
          await win.webContents.printToPDF({ printBackground: true, preferCSSPageSize: true, pageSize: "A4" })
        ).toString("base64");
      });
      writeFileSync(
        path.join(
          outputs,
          sample === "real" ? "customer-transactions.pdf" : "customer-transactions-many.pdf",
        ),
        Buffer.from(data, "base64"),
      );
      await preview.close();
      await dialog.getByRole("button", { name: "ST-000001", exact: true }).click();
      const accounts = page.getByRole("dialog", { name: "الحسابات", exact: true });
      await expect(accounts.getByRole("complementary", { name: "ST-000001", exact: true })).toBeVisible();
      await expect(accounts.getByRole("complementary", { name: "سند مالي جديد", exact: true })).toHaveCount(
        0,
      );
      await openHistory();
      await dialog.getByRole("button", { name: "فاتورة #10", exact: true }).first().click();
      await expect(page.getByRole("complementary", { name: "الطلب #10", exact: true })).toBeVisible();
      expect(
        stub.bodies.filter(
          (row) => row.path.startsWith("/api/finance") || row.path.startsWith("/api/v1/desktop/customers"),
        ),
      ).toHaveLength(0);
      expect(errors).toEqual([]);
    } catch (error) {
      await cleanup();
      throw error;
    }
    await cleanup();
  });
