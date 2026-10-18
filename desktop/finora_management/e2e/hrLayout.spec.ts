import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("all employee tabs keep a useful table area at desktop sizes", async () => {
  test.setTimeout(180000);
  const appDir = path.resolve(__dirname, "..");
  const phase = process.env.FINORA_HR_LAYOUT_PHASE === "before" ? "before" : "after";
  const output = path.join(appDir, "..", "..", "tests", "_artifacts", "hr-layout", phase);
  mkdirSync(output, { recursive: true });
  const stub = await startFinoraStub({ hr: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-hr-layout-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-hr-layout-")
  )
    throw new Error("Unsafe HR layout test cleanup");
  const app = await electron.launch({
    args: [appDir],
    cwd: appDir,
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const samples: object[] = [];
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const login = page.getByRole("form", { name: "تسجيل الدخول إلى FINORA" });
    await login.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await login.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await login.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await login.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page.getByRole("dialog", { name: "المزيد" }).getByText("الموظفون", { exact: true }).click();
    const panel = page.getByRole("dialog", { name: "الموظفون", exact: true });
    const tabs = ["الموظفون", "الحضور والدوام", "الرواتب", "السلف والعمولات", "الإجازات", "إدارة الموارد"];
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, size) => {
          const window = BrowserWindow.getAllWindows()[0];
          window?.setMinimumSize(900, 650);
          window?.setContentSize(size.width, size.height);
        },
        { width, height },
      );
      for (const [index, name] of tabs.entries()) {
        await panel.getByRole("tab", { name, exact: true }).click();
        const region = panel
          .getByRole("region")
          .filter({ has: page.getByRole("table") })
          .first();
        if (phase === "after") await expect(region).toBeVisible();
        await expect(region).toHaveAttribute("aria-busy", "false");
        const area = await region.evaluate((element) => element.getBoundingClientRect().toJSON());
        const dialog = await panel.boundingBox();
        samples.push({ width, height, tab: name, area, dialog });
        await page.screenshot({ path: path.join(output, `${width}-${index}.png`) });
        if (phase === "after") {
          expect(area?.height, `${name} table height at ${width}`).toBeGreaterThanOrEqual(260);
          expect(area?.width, `${name} table width at ${width}`).toBeGreaterThan(
            (dialog?.width || width) * 0.8,
          );
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
            true,
          );
        }
      }
    }
    if (phase === "after") {
      await panel.getByRole("tab", { name: "الموظفون", exact: true }).click();
      const summary = panel.getByRole("button", { name: "ملخص الموظفين", exact: true });
      await expect(summary).toHaveAttribute("aria-expanded", "false");
      await summary.click();
      await expect(summary).toHaveAttribute("aria-expanded", "true");
      await expect(panel.getByText("إجمالي الموظفين", { exact: true })).toBeVisible();
      await page.screenshot({ path: path.join(output, "1024-summary.png") });
      await summary.click();
      await panel.getByText("تصفية", { exact: true }).click();
      await panel.getByLabel("القسم", { exact: true }).selectOption("1");
      await expect(panel.getByLabel("القسم", { exact: true })).toHaveValue("1");
      await panel.getByLabel("القسم", { exact: true }).selectOption("");
      await panel.getByText("تصفية", { exact: true }).click();
      const region = panel.getByRole("region", { name: "قائمة الموظفين", exact: true });
      const before = await region.boundingBox();
      await region
        .getByRole("row")
        .filter({ hasText: "أحمد محمد علي" })
        .getByRole("button", { name: "فتح", exact: true })
        .click();
      await expect(
        panel.getByRole("complementary").getByRole("heading", { name: "أحمد محمد علي" }),
      ).toBeVisible();
      const withProfile = await region.boundingBox();
      expect(withProfile?.width).toBe(before?.width);
      expect(withProfile?.height).toBe(before?.height);
      await page.screenshot({ path: path.join(output, "1024-profile.png") });
      await panel.getByRole("button", { name: "توسيع الملف", exact: true }).click();
      expect((await panel.getByRole("complementary").boundingBox())?.width).toBeGreaterThan(800);
      await page.screenshot({ path: path.join(output, "1024-profile-expanded.png") });
      await panel.getByRole("button", { name: "تصغير الملف", exact: true }).click();
      expect((await region.boundingBox())?.width).toBe(before?.width);
      await panel.getByRole("button", { name: "إغلاق ملف الموظف", exact: true }).click();
    }
    expect(errors).toEqual([]);
  } finally {
    writeFileSync(path.join(output, "measurements.json"), JSON.stringify(samples, null, 2));
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
