import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("stock operations use real FIFO, loss/reversal, original recovery and printable documents through Electron", async () => {
  test.setTimeout(240000);
  const root = path.resolve(__dirname, "../../.."),
    outputs = path.join(root, "tests/_artifacts/erp-stock-operations");
  mkdirSync(outputs, { recursive: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-stock-ops-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-stock-ops-")
  )
    throw Error("Unsafe test cleanup");
  const installed = "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe";
  const server = spawn(
    process.env.FINORA_TEST_PYTHON ?? (existsSync(installed) ? installed : "python"),
    [path.join(root, "tests/_artifacts/erp-regression/stock_electron_server.py")],
    {
      cwd: root,
      env: { ...process.env, FINORA_STOCK_UI_TEST: "1", PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
      windowsHide: true,
    },
  );
  let text = "";
  const url = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => reject(Error("Stock test backend did not start")), 60000);
    server.stdout.on("data", (chunk) => {
      text += String(chunk);
      const match = /STOCK_TEST_READY (\{[^\r\n]+\})/.exec(text);
      if (match) {
        clearTimeout(timer);
        resolve((JSON.parse(match[1] ?? "{}") as { url: string }).url);
      }
    });
    server.once("error", reject);
    server.once("exit", (code) => {
      clearTimeout(timer);
      reject(Error(`Stock backend exited ${code}`));
    });
  });
  const stub = await startFinoraStub({ stockOperationsServer: url, dropFirstStockWriteoffResponse: true });
  let app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const state = async () =>
    (await (await fetch(`${url}/__state__`)).json()) as {
      source: { quantity: number };
      cash: number;
      value: number;
      journals: number;
      profit: number;
      stock_loss: number;
    };
  try {
    const page = await app.firstWindow(),
      errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المنتجات", exact: true }).first().click();
    await page.getByRole("button", { name: "إدارة المخزون", exact: true }).click();
    await expect(page.getByRole("region", { name: "أرصدة المخزون حسب الموقع" })).toBeVisible();
    expect((await state()).value).toBe(1200);
    await page.getByRole("button", { name: "تحويل جديد", exact: true }).click();
    await expect(page.getByLabel("موقع المخزون", { exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "إعادة الطلب", exact: true })).toBeDisabled();
    await page.getByLabel("إضافة صنف نقل").click();
    await page.getByLabel("كمية صنف نقل").fill("3");
    await page.getByLabel("سبب العملية المخزنية").fill("توزيع فعلي موثق");
    await page.getByRole("button", { name: "حفظ المسودة", exact: true }).click();
    await expect(page.getByRole("complementary", { name: "تفاصيل تحويل المخزون" })).toBeVisible();
    expect((await state()).source.quantity).toBe(6);
    await page.getByRole("button", { name: "إرسال التحويل", exact: true }).click();
    await page.getByLabel("سبب العملية المخزنية").fill("تم تسليم القطع للمندوب");
    await page.getByRole("button", { name: "تأكيد وحفظ", exact: true }).click();
    await expect(page.getByRole("button", { name: "استلام التحويل", exact: true })).toBeVisible();
    expect((await state()).source.quantity).toBe(3);
    expect((await state()).value).toBe(1200);
    await page.getByRole("button", { name: "استلام التحويل", exact: true }).click();
    await page.getByLabel("سبب العملية المخزنية").fill("استلمت القطع في الوجهة");
    await page.getByRole("button", { name: "تأكيد وحفظ", exact: true }).click();
    await expect(
      page.getByRole("complementary", { name: "تفاصيل تحويل المخزون" }).getByText(/مستلم/).first(),
    ).toBeVisible();
    const print = async (name: string) => {
      const next = app.waitForEvent("window");
      await (await app.firstWindow()).getByRole("button", { name: "طباعة السند", exact: true }).click();
      const preview = await next;
      await expect(preview.getByRole("heading")).toBeVisible();
      const pdf = await app.evaluate(async ({ BrowserWindow }) => {
        const win = BrowserWindow.getAllWindows().find(
          (w) =>
            w.webContents.getURL().includes("/stock-operations/") &&
            w.webContents.getURL().endsWith("/print"),
        );
        if (!win) throw Error("Missing stock print preview");
        return (
          await win.webContents.printToPDF({ printBackground: true, preferCSSPageSize: true })
        ).toString("base64");
      });
      writeFileSync(path.join(outputs, `${name}.pdf`), Buffer.from(pdf, "base64"));
      await preview.close();
    };
    await print("transfer");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "أرصدة المواقع", exact: true }).click();
    await page.getByLabel("تلف صنف نقل").click();
    await page.getByLabel("سبب العملية المخزنية").fill("قطعة تالفة فعلياً");
    await page.getByRole("button", { name: "ترحيل التلف", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "طلبك محفوظ للمراجعة" })).toBeVisible({
      timeout: 45000,
    });
    expect((await state()).source.quantity).toBe(2);
    await page.getByRole("button", { name: "إغلاق النموذج", exact: true }).click();
    await app.close();
    app = await electron.launch({
      args: [path.resolve(__dirname, "..")],
      cwd: path.resolve(__dirname, ".."),
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
    const restarted = await app.firstWindow();
    await restarted.getByRole("button", { name: "المنتجات", exact: true }).first().click();
    await restarted.getByRole("button", { name: "إدارة المخزون", exact: true }).click();
    await restarted.getByText(/طلبات مخزون محفوظة للمراجعة/).click();
    await restarted.getByRole("button", { name: "مراجعة نفس الطلب", exact: true }).click();
    await restarted.getByRole("button", { name: "مراجعة الطلب", exact: true }).click();
    await expect(restarted.getByRole("complementary", { name: "تفاصيل سند التلف" })).toBeVisible();
    expect((await state()).source.quantity).toBe(2);
    expect((await state()).cash).toBe(20000000);
    const sent = stub.bodies.filter((row) => row.path.endsWith("/branch/writeoffs"));
    expect(sent).toHaveLength(2);
    expect(sent[0]?.body).toEqual(sent[1]?.body);
    await print("writeoff");
    expect((await state()).profit).toBe(-250);
    expect((await state()).stock_loss).toBe(250);
    await restarted.getByRole("button", { name: "التقارير", exact: true }).first().click();
    const reports = restarted.getByRole("dialog", { name: "التقارير", exact: true });
    await reports.getByRole("button", { name: "صافي الربح — فتح التقرير", exact: true }).click();
    await expect(
      reports
        .getByRole("table", { name: "قائمة الدخل" })
        .getByRole("row")
        .filter({ hasText: "صافي خسائر المخزون / العكس" }),
    ).toContainText("250");
    await reports.screenshot({ path: path.join(outputs, "stock-loss-profit.png"), animations: "disabled" });
    await reports.getByRole("button", { name: /^طباعة/ }).click();
    await expect
      .poll(
        () =>
          app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows().some(
              (w) => w.isVisible() && w.getTitle().startsWith("معاينة الطباعة"),
            ),
          ),
        { timeout: 30000 },
      )
      .toBe(true);
    const reportPreview = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find(
        (w) => w.isVisible() && w.getTitle().startsWith("معاينة الطباعة"),
      );
      if (!win) throw Error("Missing native PDF viewer");
      return { id: win.id, url: win.webContents.getURL() };
    });
    const printedFile = fileURLToPath(reportPreview.url);
    if (
      path.dirname(printedFile) !== path.resolve(tmpdir()) ||
      !path.basename(printedFile).startsWith("finora-print-")
    )
      throw Error("Unexpected report PDF path");
    writeFileSync(path.join(outputs, "stock-loss-report.pdf"), readFileSync(printedFile));
    await app.evaluate(({ BrowserWindow }, id) => BrowserWindow.fromId(id)?.close(), reportPreview.id);
    await restarted.getByRole("button", { name: "المنتجات", exact: true }).first().click();
    await restarted.getByRole("button", { name: "عكس السند", exact: true }).click();
    await restarted.getByLabel("سبب العملية المخزنية").fill("القطعة سليمة والتلف سجل بالخطأ");
    await restarted.getByRole("button", { name: "تأكيد وحفظ", exact: true }).click();
    await expect(
      restarted.getByRole("complementary", { name: "تفاصيل سند التلف" }).getByText(/سند عكس/),
    ).toBeVisible();
    expect((await state()).source.quantity).toBe(3);
    expect((await state()).value).toBe(1200);
    expect((await state()).profit).toBe(0);
    expect((await state()).stock_loss).toBe(0);
    await restarted.keyboard.press("Escape");
    await restarted.getByRole("button", { name: "أرصدة المواقع", exact: true }).click();
    await restarted.getByLabel("حد طلب صنف نقل").click();
    await restarted.getByRole("spinbutton", { name: "حد إعادة الطلب", exact: true }).fill("5");
    await restarted.getByLabel("الرصيد المستهدف", { exact: true }).fill("9");
    await restarted.getByLabel("سبب العملية المخزنية").fill("حاجة الفرع التشغيلية");
    await restarted.getByRole("button", { name: "تأكيد وحفظ", exact: true }).click();
    await expect(
      restarted.getByRole("complementary", { name: "حد إعادة الطلب", exact: true }),
    ).not.toBeVisible();
    await restarted.getByRole("button", { name: "إعادة الطلب", exact: true }).click();
    await expect(restarted.getByRole("columnheader", { name: "كمية مقترحة" })).toBeVisible();
    await expect(
      restarted
        .getByRole("region", { name: "أرصدة المخزون حسب الموقع" })
        .getByRole("row")
        .filter({ hasText: "صنف نقل" })
        .getByRole("cell")
        .filter({ hasText: /^6$/ }),
    ).toBeVisible();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setMinimumSize(900, 650));
    for (const width of [1536, 1180, 1024]) {
      await app.evaluate(
        ({ BrowserWindow }, width) => BrowserWindow.getAllWindows()[0]?.setSize(width, 800),
        width,
      );
      await expect(restarted.getByRole("region", { name: "أرصدة المخزون حسب الموقع" })).toBeVisible();
      expect(await restarted.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
        true,
      );
      expect(
        await restarted
          .getByRole("region", { name: "أرصدة المخزون حسب الموقع" })
          .evaluate((element) => element.scrollWidth <= element.clientWidth),
      ).toBe(true);
      await restarted.screenshot({ path: path.join(outputs, `stock-${width}.png`), animations: "disabled" });
    }
    expect(errors).toEqual([]);
    writeFileSync(path.join(outputs, "verified-state.json"), JSON.stringify(await state(), null, 2));
  } catch (error) {
    const current = await app.firstWindow();
    console.log((await current.locator("body").innerText()).slice(-4000));
    await current.screenshot({ path: path.join(outputs, "failure.png") });
    throw error;
  } finally {
    await app.close();
    await stub.close();
    await fetch(`${url}/__shutdown__`);
    rmSync(profile, { recursive: true, force: true });
  }
});
