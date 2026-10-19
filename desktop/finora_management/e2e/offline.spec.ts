import { closeIsolatedApp } from "./closeIsolatedApp";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test, type ElectronApplication } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";
import type { FinoraDesktopBridge } from "../shared/ipc";
import type { Page } from "@playwright/test";
const localStatus = (page: Page) =>
  page.evaluate(() => {
    const bridge = (window as unknown as { finoraDesktop: FinoraDesktopBridge }).finoraDesktop.offline;
    if (!bridge) throw new Error("Offline IPC is unavailable");
    return bridge.status();
  });
const syncLocal = (page: Page) =>
  page.evaluate(() => {
    const bridge = (window as unknown as { finoraDesktop: FinoraDesktopBridge }).finoraDesktop.offline;
    if (!bridge) throw new Error("Offline IPC is unavailable");
    return bridge.synchronize();
  });

test("POS cash sale offline after restart consumes its device quota and synchronizes once", async () => {
  const stub = await startFinoraStub();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-pos-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-pos-e2e-")
  )
    throw new Error("Unsafe test profile");
  const appDir = path.resolve(__dirname, "..");
  let app: ElectronApplication | undefined;
  const launch = () =>
    electron.launch({
      executablePath: process.env.FINORA_E2E_EXECUTABLE,
      args: process.env.FINORA_E2E_EXECUTABLE ? [] : [appDir],
      cwd: appDir,
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
  try {
    app = await launch();
    let page = await app.firstWindow();
    const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await form.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await form.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await form.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await form.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "نقطة البيع", exact: true }).click();
    let pos = page.getByRole("dialog", { name: "نقطة البيع", exact: true });
    await pos.getByRole("button", { name: "إضافة شاشة LG 50 بوصة", exact: true }).click();
    await pos.getByLabel("البحث عن زبون", { exact: true }).fill("علي");
    await page.getByRole("button", { name: /علي حسين.*07705556633/ }).click();
    await pos.getByRole("button", { name: "حجز كميات السلة للجهاز", exact: true }).click();
    await expect(pos.getByRole("checkbox", { name: "البيع من حصة هذا الجهاز", exact: true })).toBeChecked();
    await expect.poll(async () => (await localStatus(page)).stock?.rows[0]?.available).toBe(1);
    stub.setOnline(false);
    await closeIsolatedApp(app);
    app = undefined;
    app = await launch();
    page = await app.firstWindow();
    await page.getByRole("button", { name: "نقطة البيع", exact: true }).click();
    pos = page.getByRole("dialog", { name: "نقطة البيع", exact: true });
    await pos.getByRole("button", { name: "إضافة شاشة LG 50 بوصة", exact: true }).click();
    await pos.getByLabel("البحث عن زبون", { exact: true }).fill("علي");
    await page.getByRole("button", { name: /علي حسين.*07705556633/ }).click();
    await pos.getByRole("button", { name: "خيارات التنفيذ", exact: true }).click();
    await page.getByRole("menuitem", { name: "تنفيذ بدون طباعة", exact: true }).click();
    await expect(page.getByText(/تم اعتماد البيع المحلي #/)).toBeVisible();
    const status = await localStatus(page);
    expect(status.pending).toBe(1);
    expect(status.stock?.rows[0]?.available).toBe(0);
    expect(status.operations[0]?.kind).toBe("pos");
    expect(
      stub.bodies.some((b) =>
        ["/pos/create-order", "/orders/payment", "/api/v1/desktop/sync/pos-sale"].includes(b.path),
      ),
    ).toBe(false);
    await page.screenshot({ path: path.join(appDir, "test-results", "offline-pos-sale.png") });
    await closeIsolatedApp(app);
    app = undefined;
    app = await launch();
    page = await app.firstWindow();
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await expect.poll(async () => (await localStatus(page)).pending).toBe(1);
    stub.setOnline(true);
    await syncLocal(page);
    await syncLocal(page);
    const synced = await localStatus(page);
    expect(synced.operations[0]?.invoiceNo).toBe("10047");
    const submissions = stub.bodies.filter((b) => b.path === "/api/v1/desktop/sync/pos-sale");
    expect(submissions).toHaveLength(1);
    expect(submissions[0]?.body).toMatchObject({
      sale: { payment: "cash", accountId: 4, total: 282000 },
      reservations: [{ qty: 1 }],
    });
  } finally {
    if (app) await closeIsolatedApp(app);
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});

test("complete download supplies unvisited supplier details and colored products offline", async () => {
  const stub = await startFinoraStub();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-snapshot-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-snapshot-e2e-")
  )
    throw new Error("Unsafe test profile");
  const appDir = path.resolve(__dirname, "..");
  let app: ElectronApplication | undefined;
  const launch = () =>
    electron.launch({
      args: [appDir],
      cwd: appDir,
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
  try {
    app = await launch();
    let page = await app.firstWindow();
    const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await form.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await form.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await form.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await form.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    await page.getByRole("button", { name: "الأوفلاين والمزامنة", exact: true }).click();
    await page.getByRole("button", { name: "تنزيل البيانات", exact: true }).click();
    await expect(page.getByText("النسخة المحلية مكتملة", { exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(appDir, "test-results", "offline-snapshot.png") });
    expect(stub.requests.some((r) => r.includes("/suppliers/api/9"))).toBe(false);
    expect(stub.requests.some((r) => r.includes("/suppliers/api/sale-products"))).toBe(false);
    stub.setOnline(false);
    await closeIsolatedApp(app);
    app = undefined;
    app = await launch();
    page = await app.firstWindow();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page
      .getByRole("dialog", { name: "المزيد" })
      .getByRole("button", { name: "الموردين حسابات الموردين والمشتريات والدفعات", exact: true })
      .click();
    const workbench = page.getByRole("dialog", { name: "الموردين", exact: true });
    await workbench.getByRole("searchbox").fill("مؤسسة الثقة");
    await workbench
      .getByRole("row")
      .filter({ hasText: "مؤسسة الثقة" })
      .getByRole("button", { name: "فتح", exact: true })
      .click();
    const details = page.getByRole("complementary", { name: "تفاصيل المورد" });
    await details.getByRole("tab", { name: "المبيعات للمورد", exact: true }).click();
    await details.getByRole("button", { name: "بيع للمورد", exact: true }).click();
    const sale = page.getByRole("dialog", { name: "بيع للمورد", exact: true });
    await sale.getByRole("searchbox").fill("6290000000099");
    await sale.getByRole("button", { name: /سماعة ملونة/ }).click();
    await sale.getByLabel("لون سماعة ملونة").selectOption("أسود");
    await sale.getByRole("button", { name: "حفظ مسودة للمزامنة", exact: true }).click();
    await expect(sale).not.toBeVisible();
    expect(stub.bodies.filter((b) => b.path === "/api/v1/desktop/sync/supplier-sale")).toHaveLength(0);
  } finally {
    if (app) await closeIsolatedApp(app);
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});

test("encrypted offline restart, local sale draft and reconnect replay", async () => {
  const stub = await startFinoraStub();
  const profile = mkdtempSync(path.join(tmpdir(), "finora-offline-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-offline-e2e-")
  )
    throw new Error("Unsafe test profile");
  const appDir = path.resolve(__dirname, "..");
  let app: ElectronApplication | undefined;
  const launch = () =>
    electron.launch({
      args: [appDir],
      cwd: appDir,
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
  try {
    app = await launch();
    let page = await app.firstWindow();
    const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await form.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await form.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await form.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await form.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page
      .getByRole("dialog", { name: "المزيد" })
      .getByRole("button", { name: "الموردين حسابات الموردين والمشتريات والدفعات", exact: true })
      .click();
    let workbench = page.getByRole("dialog", { name: "الموردين", exact: true });
    await workbench
      .getByRole("row")
      .filter({ hasText: "شركة الأمل" })
      .getByRole("button", { name: "فتح", exact: true })
      .click();
    let details = page.getByRole("complementary", { name: "تفاصيل المورد" });
    await details.getByRole("tab", { name: "المبيعات للمورد", exact: true }).click();
    await details.getByRole("button", { name: "بيع للمورد", exact: true }).click();
    let sale = page.getByRole("dialog", { name: "بيع للمورد", exact: true });
    await sale.getByRole("searchbox").fill("6290000000011");
    await expect(sale.getByRole("button", { name: /شاشة LG 50/ })).toBeVisible();
    await sale.getByRole("button", { name: "إلغاء", exact: true }).click();
    stub.setOnline(false);
    await closeIsolatedApp(app);
    app = undefined;
    app = await launch();
    page = await app.firstWindow();
    await expect(page.getByRole("button", { name: "المزيد", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page
      .getByRole("dialog", { name: "المزيد" })
      .getByRole("button", { name: "الموردين حسابات الموردين والمشتريات والدفعات", exact: true })
      .click();
    workbench = page.getByRole("dialog", { name: "الموردين", exact: true });
    await workbench
      .getByRole("row")
      .filter({ hasText: "شركة الأمل" })
      .getByRole("button", { name: "فتح", exact: true })
      .click();
    details = page.getByRole("complementary", { name: "تفاصيل المورد" });
    await details.getByRole("tab", { name: "المبيعات للمورد", exact: true }).click();
    await details.getByRole("button", { name: "بيع للمورد", exact: true }).click();
    sale = page.getByRole("dialog", { name: "بيع للمورد", exact: true });
    await sale.getByRole("searchbox").fill("6290000000011");
    await sale.getByRole("button", { name: /شاشة LG 50/ }).click();
    await sale.getByRole("button", { name: "حفظ مسودة للمزامنة", exact: true }).click();
    await expect(sale).not.toBeVisible();
    expect(stub.bodies.filter((b) => b.path === "/api/v1/desktop/sync/supplier-sale")).toHaveLength(0);
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    await page.getByRole("button", { name: "الأوفلاين والمزامنة", exact: true }).click();
    await expect(page.getByText("بانتظار المزامنة", { exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(appDir, "test-results", "offline-queue.png") });
    const encrypted = readFileSync(path.join(profile, "offline", "business.sqlite.enc"));
    expect(encrypted.toString()).not.toContain("شركة الأمل");
    expect(encrypted.toString()).not.toContain(STUB_CREDENTIALS.password);
    await closeIsolatedApp(app);
    app = undefined;
    app = await launch();
    page = await app.firstWindow();
    await expect(page.getByRole("button", { name: "الإعدادات", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    await page.getByRole("button", { name: "الأوفلاين والمزامنة", exact: true }).click();
    await expect(page.getByText("بانتظار المزامنة", { exact: true })).toBeVisible();
    stub.setOnline(true);
    await expect(page.getByText("تم التسجيل", { exact: true })).toBeVisible({ timeout: 20_000 });
    expect(stub.bodies.filter((b) => b.path === "/api/v1/desktop/sync/supplier-sale")).toHaveLength(1);
    await page.screenshot({ path: path.join(appDir, "test-results", "offline-synchronized.png") });
  } finally {
    if (app) await closeIsolatedApp(app);
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
