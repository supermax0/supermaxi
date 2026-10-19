import { closeIsolatedApp } from "./closeIsolatedApp";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test, type ElectronApplication } from "@playwright/test";
import { startAuditServer } from "./auditServer";
import type { FinoraDesktopBridge } from "../shared/ipc";
import { auditLocalSchema } from "../shared/inventoryAudit";

test("Desktop audit keeps encrypted dated counts across offline restart and synchronizes once to real stock services", async () => {
  test.setTimeout(180000);
  const server = await startAuditServer();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-smart-audit-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-smart-audit-e2e-")
  )
    throw Error("Unsafe profile cleanup");
  const artifacts = path.resolve(__dirname, "../../../tests/_artifacts/smart-inventory-audit");
  mkdirSync(artifacts, { recursive: true });
  let app: ElectronApplication | null = null;
  const launch = () =>
    electron.launch({
      args: [path.resolve(__dirname, "..")],
      cwd: path.resolve(__dirname, ".."),
      env: { ...process.env, FINORA_SERVER_URL: server.url, FINORA_USER_DATA_DIR: profile },
    });
  const state = async () =>
    (await fetch(`${server.backendUrl}/__audit_test/state`)).json() as Promise<{
      stocks: number[];
      journals: number;
      events: number;
    }>;
  try {
    app = await launch();
    let page = await app.firstWindow();
    page.setDefaultTimeout(15000);
    await page.getByLabel("معرف الشركة").fill(server.tenant);
    await page.getByLabel("اسم المستخدم").fill("isolated-test");
    await page.getByLabel("كلمة المرور").fill("isolated-test");
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المنتجات", exact: true }).click();
    let products = page.getByRole("dialog", { name: "إدارة المنتجات", exact: true });
    await products.getByRole("button", { name: "جرد المخزون", exact: true }).click();
    await products.getByRole("button", { name: "جلسة جديدة", exact: true }).click();
    const create = page.getByRole("dialog", { name: "بدء جلسة جرد", exact: true });
    await create.getByLabel("عنوان جلسة الجرد").fill("جرد الديسكتوب دون اتصال");
    await create.getByRole("checkbox").first().check();
    await create.getByRole("button", { name: "بدء الجرد", exact: true }).click();
    await products.getByRole("button", { name: "تنزيل هذا الموقع للعد بدون إنترنت", exact: true }).click();
    await expect
      .poll(async () => {
        const response = await page.evaluate(() =>
          (window as unknown as { finoraDesktop: FinoraDesktopBridge }).finoraDesktop.finora.request({
            method: "GET",
            path: "/api/v1/desktop/inventory-audits/local/status",
          }),
        );
        if (!response.ok) return -1;
        return auditLocalSchema.parse((response.data as { data: unknown }).data).prepared_records;
      })
      .toBe(2);
    server.setOnline(false);
    await closeIsolatedApp(app);
    app = null;
    app = await launch();
    page = await app.firstWindow();
    page.setDefaultTimeout(15000);
    await page.getByRole("button", { name: "المنتجات", exact: true }).click();
    products = page.getByRole("dialog", { name: "إدارة المنتجات", exact: true });
    await products.getByRole("button", { name: "جرد المخزون", exact: true }).click();
    await products.getByRole("button", { name: /جرد الديسكتوب دون اتصال/ }).click();
    await products.getByLabel("بحث أصناف الجرد").fill("TV55");
    await products.getByLabel("نتائج بحث الجرد").getByRole("button").first().click();
    await products.getByLabel("العدد الفعلي", { exact: true }).fill("10");
    await products.getByLabel("ملاحظة العد").fill("OFFLINE-AUDIT-PRIVATE-NOTE");
    await products.getByRole("button", { name: "إضافة إلى الجرد", exact: true }).click();
    await expect(products.getByLabel("مزامنة الجرد")).toContainText("بانتظار المزامنة");
    await products.getByLabel("وضع مسح الجرد").selectOption("count");
    await products.getByLabel("بحث أصناف الجرد").fill("88055");
    await products.getByLabel("بحث أصناف الجرد").press("Enter");
    await expect(
      products
        .locator("article")
        .filter({ hasText: "شاشة 55" })
        .getByText(/الفعلي/),
    ).toContainText("11");
    expect((await state()).stocks).toEqual([12, 4, 0]);
    expect(
      readFileSync(path.join(profile, "offline/business.sqlite.enc")).includes(
        Buffer.from("OFFLINE-AUDIT-PRIVATE-NOTE"),
      ),
    ).toBe(false);
    const countedCard = products.locator("article").filter({ hasText: "شاشة 55" });
    await countedCard.scrollIntoViewIfNeeded();
    await expect(countedCard).toBeInViewport({ ratio: 1 });
    await page.screenshot({
      path: path.join(artifacts, "desktop-offline-count.png"),
      animations: "disabled",
    });
    await closeIsolatedApp(app);
    app = null;
    server.setOnline(true);
    app = await launch();
    page = await app.firstWindow();
    page.setDefaultTimeout(15000);
    await page.getByRole("button", { name: "المنتجات", exact: true }).click();
    products = page.getByRole("dialog", { name: "إدارة المنتجات", exact: true });
    await products.getByRole("button", { name: "جرد المخزون", exact: true }).click();
    await products.getByRole("button", { name: /جرد الديسكتوب دون اتصال/ }).click();
    await products.getByRole("button", { name: "مزامنة العد", exact: true }).click();
    await expect(products.getByRole("button", { name: "مزامنة العد", exact: true })).toHaveCount(0);
    const result = await state();
    expect(result.stocks).toEqual([12, 4, 0]);
    expect(result.journals).toBe(0);
    const countEvents = result.events;
    await products.getByLabel("تحديث الجرد").click();
    expect((await state()).events).toBe(countEvents);
    await products.locator("article").filter({ hasText: "شاشة 55" }).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(artifacts, "desktop-synchronized-count.png"),
      animations: "disabled",
    });
    await products.getByRole("button", { name: "إيقاف مؤقت", exact: true }).click();
    await expect(products.getByRole("button", { name: "استئناف الجرد", exact: true })).toBeVisible();
    await products.getByRole("button", { name: "استئناف الجرد", exact: true }).click();
    await expect(products.getByRole("button", { name: "إيقاف مؤقت", exact: true })).toBeVisible();
    expect((await state()).stocks).toEqual([12, 4, 0]);
    expect((await state()).journals).toBe(0);
  } catch (error) {
    console.log(server.log());
    if (app) console.log((await (await app.firstWindow()).locator("body").innerText()).slice(-5000));
    throw error;
  } finally {
    if (app) await closeIsolatedApp(app);
    await server.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
