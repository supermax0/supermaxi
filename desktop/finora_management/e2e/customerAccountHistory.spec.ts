import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("historical customer statement renders actual server evidence, filters, exports and prints through Electron", async () => {
  test.setTimeout(150000);
  const outputs = path.resolve(__dirname, "../../../tests/_artifacts/erp-customers");
  mkdirSync(outputs, { recursive: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-account-history-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-account-history-")
  )
    throw Error("Unsafe cleanup");
  const data = JSON.parse(readFileSync(path.join(outputs, "account-history-real.json"), "utf8")) as Record<
    string,
    unknown
  >;
  const stub = await startFinoraStub({
    customers: true,
    finance: true,
    customerAccountHistory: {
      data,
      html: readFileSync(path.join(outputs, "account-history-real.html"), "utf8"),
      csv: readFileSync(path.join(outputs, "account-history-real.csv"), "utf8"),
    },
  });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    const more = page.getByRole("dialog", { name: "المزيد", exact: true });
    await more.getByRole("combobox").fill("زبائن");
    await more.getByRole("option").filter({ hasText: "العملاء" }).click();
    const customers = page.getByRole("dialog", { name: "العملاء", exact: true });
    await expect(customers).toBeVisible();
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "بحث سريع", exact: true });
    await palette.getByRole("textbox").fill("العملاء");
    await expect(palette.getByRole("option")).toHaveCount(1);
    await palette.getByRole("textbox").press("Enter");
    await customers.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
    await customers.getByRole("button", { name: "كشف الحساب التاريخي", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "كشف الحساب التاريخي — أحمد العميل", exact: true });
    await expect(dialog.getByRole("columnheader", { name: "رصيد نهاية اليوم" })).toBeVisible();
    await expect(dialog.getByText(/إثبات \/ زيادة أصل فاتورة/).first()).toBeVisible();
    await expect(dialog.getByText(/نهاية الفترة/)).toContainText("400,000");
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setMinimumSize(800, 600));
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0]?.setSize(size.width, size.height),
        { width, height },
      );
      const bounds = await dialog.getByRole("region", { name: "جدول حركات التحصيل" }).boundingBox();
      expect(bounds?.height).toBeGreaterThanOrEqual(200);
      await expect(dialog.getByRole("button", { name: "طباعة الحركات / PDF" })).toBeInViewport();
      await page.screenshot({
        path: path.join(outputs, `account-history-${width}.png`),
        animations: "disabled",
      });
    }
    await dialog.getByLabel("بداية فترة الكشف").fill("2026-01-01");
    const destination = path.join(profile, "history.csv");
    await app.evaluate(
      ({ BrowserWindow }, file) =>
        BrowserWindow.getAllWindows()[0]?.webContents.session.once("will-download", (_event, item) =>
          item.setSavePath(file),
        ),
      destination,
    );
    await dialog.getByRole("button", { name: "تصدير كل الحركات" }).click();
    await expect.poll(() => existsSync(destination)).toBe(true);
    expect(readFileSync(destination, "utf8")).toContain("كشف حساب تاريخي");
    const next = app.waitForEvent("window");
    await dialog.getByRole("button", { name: "طباعة الحركات / PDF" }).click();
    const preview = await next;
    await expect(preview.getByRole("heading", { name: "FINORA — كشف الحساب التاريخي" })).toBeVisible();
    const pdf = await app.evaluate(async ({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find((win) =>
        win.webContents.getURL().includes("/account-history/print"),
      );
      if (!window) throw Error("History print preview missing");
      return (
        await window.webContents.printToPDF({
          printBackground: true,
          preferCSSPageSize: true,
          pageSize: "A4",
          landscape: true,
        })
      ).toString("base64");
    });
    writeFileSync(path.join(outputs, "account-history.pdf"), Buffer.from(pdf, "base64"));
    expect(errors).toEqual([]);
  } catch (error) {
    console.log((await (await app.firstWindow()).locator("body").innerText()).slice(-4500));
    throw error;
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
