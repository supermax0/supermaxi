import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { DownloadItem, Event as ElectronEvent } from "electron";
import { _electron as electron, expect, test } from "@playwright/test";
import { startAuditServer } from "./auditServer";

test("native inventory activity reads real receipts, follows old sources and reports every filtered row", async ({
  request,
}) => {
  test.setTimeout(180000);
  const server = await startAuditServer();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-stock-history-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-stock-history-e2e-")
  )
    throw Error("Unsafe test profile cleanup");
  const outputs = path.resolve(__dirname, "../../../tests/_artifacts/erp-inventory-activity");
  mkdirSync(outputs, { recursive: true });
  let app: Awaited<ReturnType<typeof electron.launch>> | undefined;
  try {
    const seeded = await request.post(`${server.url}/__audit_test/seed-stock-history`);
    expect(seeded.ok(), await seeded.text()).toBe(true);
    const purchases = (await seeded.json()).purchases as number[];
    const state = async () => await (await request.get(`${server.url}/__audit_test/state`)).json();
    const before = await state();
    expect(before.stocks).toEqual([40, 4, 0]);
    expect(before.cash).toBe(0);
    app = await electron.launch({
      args: [path.resolve(__dirname, "..")],
      cwd: path.resolve(__dirname, ".."),
      env: { ...process.env, FINORA_SERVER_URL: server.url, FINORA_USER_DATA_DIR: profile },
    });
    const page = await app.firstWindow();
    const mainWindow = await app.browserWindow(page);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(server.tenant);
    await page.getByLabel("اسم المستخدم").fill("audit-test");
    await page.getByLabel("كلمة المرور").fill("isolated-test");
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المنتجات", exact: true }).click();
    const products = page.getByRole("dialog", { name: "إدارة المنتجات", exact: true });
    await products.getByRole("button", { name: "حركة المخزون", exact: true }).click();
    const table = products.getByRole("region", { name: "حركة المخزون" }).getByRole("table");
    const listResponse = await request.get(`${server.url}/api/v1/desktop/inventory-activity?page_size=100`);
    expect(listResponse.ok(), await listResponse.text()).toBe(true);
    const all = (await listResponse.json()).data.items as {
      id: number;
      source_type: string;
      document_id: number;
    }[];
    expect(all.filter((row) => row.source_type === "purchase")).toHaveLength(28);
    await page.screenshot({ path: path.join(outputs, "stock-initial.png"), animations: "disabled" });
    await expect(table.getByRole("row").filter({ hasText: "استلام شراء" })).toHaveCount(25);
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ] as const) {
      await mainWindow.evaluate(
        (win, size) => {
          win.setContentSize(size[0], size[1]);
        },
        [width, height] as const,
      );
      await expect(table).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const tableArea = await products.getByRole("region", { name: "حركة المخزون" }).boundingBox();
      if (!tableArea) throw Error("Stock table area missing");
      expect(tableArea.height).toBeGreaterThan(190);
      await page.screenshot({ path: path.join(outputs, `stock-${width}.png`), animations: "disabled" });
    }
    const nextWindow = app.waitForEvent("window");
    await products.getByRole("button", { name: "طباعة / PDF", exact: true }).click();
    const preview = await nextWindow;
    await expect(preview.getByRole("table").locator("tbody tr")).toHaveCount(all.length);
    await preview.evaluate(() => document.fonts.ready);
    const pdfBase64 = await app.evaluate(async ({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((w) =>
        w.webContents.getURL().includes("/inventory-activity/print"),
      );
      if (!win) throw Error("Stock activity print window missing");
      return (
        await win.webContents.printToPDF({ printBackground: true, preferCSSPageSize: true, pageSize: "A4" })
      ).toString("base64");
    });
    writeFileSync(path.join(outputs, "stock-activity.pdf"), Buffer.from(pdfBase64, "base64"));
    await preview.close();
    const csvPath = path.join(profile, "stock-activity.csv");
    await mainWindow.evaluate((win, savePath) => {
      win.webContents.session.once("will-download", (_event: ElectronEvent, item: DownloadItem) =>
        item.setSavePath(savePath),
      );
    }, csvPath);
    await products.getByRole("button", { name: "تصدير CSV", exact: true }).click();
    await expect
      .poll(() =>
        existsSync(csvPath)
          ? readFileSync(csvPath, "utf8")
              .split("\n")
              .filter((line) => line.includes("استلام شراء")).length
          : 0,
      )
      .toBe(28);
    const csv = readFileSync(csvPath, "utf8");
    expect(csv.split("\n").filter((line) => line.includes("استلام شراء"))).toHaveLength(28);
    writeFileSync(path.join(outputs, "stock-activity.csv"), csv);
    await products.getByRole("button", { name: "الصفحة التالية", exact: true }).click();
    const oldest = table.getByRole("row").filter({ hasText: "استلام شراء" }).last();
    await expect(products.getByRole("region", { name: "حركة المخزون" })).toHaveAttribute(
      "aria-busy",
      "false",
    );
    await oldest.click();
    const movement = products.getByRole("complementary", { name: "تفاصيل حركة المخزون" });
    await movement.getByRole("button", { name: "عرض المستند", exact: true }).click();
    const purchasePanel = page.getByRole("complementary", { name: "ACT-001", exact: true });
    try {
      await expect(purchasePanel).toBeVisible();
    } catch (error) {
      writeFileSync(
        path.join(outputs, "source-open-diagnostic.json"),
        JSON.stringify(
          await page.evaluate(() => ({
            dialogs: Array.from(document.querySelectorAll('[role="dialog"],[role="complementary"]')).map(
              (node) => ({
                name: node.getAttribute("aria-label"),
                text: node.textContent?.slice(0, 1200),
              }),
            ),
            alerts: Array.from(document.querySelectorAll('[role="alert"]')).map((node) => node.textContent),
          })),
          null,
          2,
        ),
      );
      await page.screenshot({ path: path.join(outputs, "source-open-failed.png") });
      throw error;
    }
    await expect(purchasePanel).toContainText("مورد اختبار الحركة");
    await expect(purchasePanel).toContainText("100");
    expect(purchases).toHaveLength(28);
    expect(await state()).toEqual(before);
    expect(errors).toEqual([]);
  } finally {
    await app?.close();
    await server.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
