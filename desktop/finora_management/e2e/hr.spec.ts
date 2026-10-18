import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";
import type { FinoraDesktopBridge } from "../shared/ipc";
const appDir = path.resolve(__dirname, "..");
const packagedExecutable = process.env.FINORA_E2E_PACKAGED_APP;
async function signIn(page: Page) {
  const form = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
  await form.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
  await form.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
  await form.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
  await form.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
}
async function openHR(page: Page) {
  const more = page.getByRole("button", { name: "المزيد", exact: true });
  await expect(more).toBeVisible();
  const existing = page.getByRole("dialog", { name: "الموظفون", exact: true });
  if (await existing.isVisible()) return existing;
  await more.click();
  await page
    .getByRole("dialog", { name: "المزيد" })
    .getByRole("button", { name: /^الموظفون الدوام والرواتب/ })
    .click();
  return page.getByRole("dialog", { name: "الموظفون", exact: true });
}
function safeRemove(profile: string) {
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-hr-e2e-")
  )
    throw new Error("Unsafe HR test cleanup");
  rmSync(profile, { recursive: true, force: true });
}
test("HR workspace preserves RTL layout and completes profile, attendance and calendar actions", async () => {
  test.setTimeout(180000);
  const stub = await startFinoraStub({ hr: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-hr-e2e-"));
  const app = await electron.launch({
    ...(packagedExecutable ? { executablePath: packagedExecutable } : {}),
    args: packagedExecutable ? [] : [appDir],
    cwd: appDir,
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  try {
    const page = await app.firstWindow();
    await signIn(page);
    const workbench = await openHR(page);
    const table = workbench.getByRole("region", { name: "قائمة الموظفين", exact: true }).getByRole("table");
    await expect(table.getByRole("row")).toHaveCount(9);
    await table
      .getByRole("row")
      .filter({ hasText: "أحمد محمد علي" })
      .getByRole("button", { name: "فتح", exact: true })
      .click();
    const panel = workbench.getByRole("complementary");
    await expect(panel.getByRole("heading", { name: "أحمد محمد علي" })).toBeVisible();
    await panel.getByRole("button", { name: "كشف الحساب المالي", exact: true }).click();
    const financial = page.getByRole("dialog", { name: "كشف الحساب المالي للموظف", exact: true });
    await expect(financial.getByRole("table", { name: "كشف مستحقات الموظف" }).getByRole("row")).toHaveCount(
      2,
    );
    await financial.getByRole("button", { name: "JE-HR-1", exact: true }).click();
    const journal = page.getByRole("dialog", { name: "المستند المحاسبي", exact: true });
    await expect(journal.getByText("استحقاق راتب تجريبي", { exact: true })).toBeVisible();
    await journal.getByRole("button", { name: "إغلاق النموذج", exact: true }).click();
    await financial.getByRole("button", { name: "إغلاق النموذج", exact: true }).click();
    const dismiss = page.getByRole("button", { name: "إخفاء", exact: true });
    if (await dismiss.isVisible()) await dismiss.click();
    for (const [width, height] of [
      [1536, 1000],
      [1180, 700],
      [1920, 1080],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, size) =>
          BrowserWindow.getAllWindows()[0]?.setContentSize(size.width, size.height),
        { width, height },
      );
      await page.waitForTimeout(300);
      await expect(panel.getByRole("button", { name: "تعديل", exact: true })).toBeVisible();
      await expect(table.getByRole("row").nth(1)).toBeInViewport({ ratio: 0.95 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(appDir, "test-results", `hr-${width}.png`) });
    }
    await panel.getByRole("button", { name: "تعديل", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "تعديل الموظف", exact: true });
    await editor.getByLabel("العنوان", { exact: true }).fill("بغداد - المنصور");
    await editor.getByLabel("اسم جهة اتصال الطوارئ", { exact: true }).fill("علي");
    await editor.getByRole("button", { name: "حفظ الموظف", exact: true }).click();
    await expect(editor).not.toBeVisible();
    await panel.getByRole("button", { name: "تسجيل حضور", exact: true }).click();
    const checkIn = page.getByRole("dialog", { name: "تسجيل حضور", exact: true });
    await checkIn.getByRole("button", { name: "حفظ", exact: true }).click();
    await expect
      .poll(async () => {
        if (!(await checkIn.isVisible())) return "closed";
        return (await checkIn.getByRole("alert").allTextContents()).join(" · ") || "pending";
      })
      .toBe("closed");
    await expect(panel.getByRole("button", { name: "تسجيل انصراف", exact: true })).toBeVisible();
    await workbench.getByRole("button", { name: "إغلاق ملف الموظف", exact: true }).click();
    await workbench.getByRole("tab", { name: "الحضور والدوام", exact: true }).click();
    await workbench
      .getByRole("row")
      .filter({ hasText: "أحمد محمد علي" })
      .getByRole("button", { name: "طلب تصحيح", exact: true })
      .click();
    const correction = page.getByRole("dialog", { name: "طلب تصحيح حضور", exact: true });
    await expect(correction.getByLabel("وقت الحضور المطلوب", { exact: true })).not.toHaveValue("");
    await correction.getByLabel("سبب طلب التصحيح", { exact: true }).fill("اختبار مسار المراجعة");
    await correction.getByRole("button", { name: "حفظ", exact: true }).click();
    await expect
      .poll(async () => {
        if (!(await correction.isVisible())) return "closed";
        return (await correction.getByRole("alert").allTextContents()).join(" · ") || "pending";
      })
      .toBe("closed");
    await workbench.getByRole("button", { name: "مركز الموافقات", exact: true }).click();
    const approvals = page.getByRole("dialog", { name: "مركز الموافقات", exact: true });
    await approvals.getByRole("button", { name: "مراجعة الطلب", exact: true }).click();
    const requests = page.getByRole("dialog", { name: "طلبات تصحيح الحضور", exact: true });
    await requests.getByRole("button", { name: "اعتماد", exact: true }).click();
    const approve = page.getByRole("dialog", { name: "اعتماد تصحيح الحضور", exact: true });
    await approve.getByLabel("سبب القرار", { exact: true }).fill("تمت المراجعة");
    await approve.getByRole("button", { name: "حفظ", exact: true }).click();
    try {
      await expect(approve).not.toBeVisible();
    } catch (error) {
      console.error(
        "HR correction approval diagnostic",
        await approve.innerText(),
        JSON.stringify(stub.bodies.filter((b) => b.path === "/hr/api/commands")),
      );
      await page.screenshot({ path: path.join(appDir, "test-results", "hr-correction-failure.png") });
      throw error;
    }
    await expect(requests.getByText("معتمد", { exact: true })).toBeVisible();
    await requests.getByRole("button", { name: "إغلاق النموذج", exact: true }).click();
    await workbench.getByRole("row").filter({ hasText: "أحمد محمد علي" }).click();
    await panel.getByRole("tab", { name: "الدوام", exact: true }).click();
    await expect(panel.getByRole("region", { name: "تقويم دوام الموظف" })).toBeVisible();
    await workbench.getByRole("button", { name: "إغلاق ملف الموظف", exact: true }).click();
    await workbench.getByRole("tab", { name: "إدارة الموارد", exact: true }).click();
    await workbench.getByRole("button", { name: "تقويم العمل", exact: true }).click();
    const calendar = page.getByRole("dialog", { name: "تقويم العمل والعطل", exact: true });
    await calendar.getByLabel("اسم المناسبة", { exact: true }).fill("عطلة اختبار");
    await calendar.getByRole("button", { name: "حفظ اليوم", exact: true }).click();
    await expect(calendar).not.toBeVisible({ timeout: 15000 });
    expect(stub.bodies.filter((b) => b.path === "/hr/api/commands")).toHaveLength(5);
  } finally {
    await app.close();
    await stub.close();
    safeRemove(profile);
  }
});

test("HR permitted snapshot survives restart and replays offline profile and attendance exactly once", async () => {
  test.setTimeout(180000);
  const stub = await startFinoraStub({ hr: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-hr-e2e-"));
  let app: ElectronApplication | undefined;
  const launch = () =>
    electron.launch({
      ...(packagedExecutable ? { executablePath: packagedExecutable } : {}),
      args: packagedExecutable ? [] : [appDir],
      cwd: appDir,
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
  try {
    app = await launch();
    let page = await app.firstWindow();
    await signIn(page);
    await openHR(page);
    const downloaded = await page.evaluate(async () => {
      const offline = (window as unknown as { finoraDesktop: FinoraDesktopBridge }).finoraDesktop.offline;
      if (!offline) throw new Error("Offline IPC unavailable");
      return offline.downloadSnapshot();
    });
    expect(downloaded.hr?.people).toBe(8);
    stub.setOnline(false);
    await app.close();
    app = undefined;
    app = await launch();
    page = await app.firstWindow();
    const workbench = await openHR(page);
    await workbench
      .getByRole("row")
      .filter({ hasText: "أحمد محمد علي" })
      .getByRole("button", { name: "فتح", exact: true })
      .click();
    const panel = workbench.getByRole("complementary");
    await panel.getByRole("button", { name: "تعديل", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "تعديل الموظف", exact: true });
    await editor.getByLabel("العنوان", { exact: true }).fill("عنوان محفوظ بدون نت");
    await editor.getByRole("button", { name: "حفظ الموظف", exact: true }).click();
    await expect(editor).not.toBeVisible();
    await panel.getByRole("button", { name: "تسجيل حضور", exact: true }).click();
    const checkIn = page.getByRole("dialog", { name: "تسجيل حضور", exact: true });
    await checkIn.getByRole("button", { name: "حفظ", exact: true }).click();
    await expect(checkIn).not.toBeVisible();
    await expect(panel.getByRole("button", { name: "تسجيل انصراف", exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(appDir, "test-results", "hr-offline.png") });
    stub.setOnline(true);
    const synchronized = await page.evaluate(async () => {
      const offline = (window as unknown as { finoraDesktop: FinoraDesktopBridge }).finoraDesktop.offline;
      if (!offline) throw new Error("Offline IPC unavailable");
      return offline.synchronize();
    });
    expect(synchronized.pending).toBe(0);
    expect(synchronized.conflicts).toBe(0);
    expect(stub.bodies.filter((b) => b.path === "/hr/api/commands")).toHaveLength(2);
  } finally {
    await app?.close();
    await stub.close();
    safeRemove(profile);
  }
});
