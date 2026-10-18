import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("core storage uses real controllers, original FIFO and separate physical confirmations", async () => {
  test.setTimeout(240000);
  const root = path.resolve(__dirname, "../../.."),
    outputs = path.join(root, "tests/_artifacts/erp-storage-locations");
  mkdirSync(outputs, { recursive: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-storage-ops-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-storage-ops-")
  )
    throw Error("Unsafe test cleanup");
  const installed = "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe";
  const server = spawn(
    process.env.FINORA_TEST_PYTHON ?? (existsSync(installed) ? installed : "python"),
    [path.join(root, "tests/_artifacts/erp-regression/storage_electron_server.py")],
    {
      cwd: root,
      env: { ...process.env, FINORA_STORAGE_UI_TEST: "1", PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
      windowsHide: true,
    },
  );
  let output = "";
  const url = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => reject(Error("Storage test backend did not start")), 60000);
    server.stdout.on("data", (chunk) => {
      output += String(chunk);
      const match = /STORAGE_TEST_READY (\{[^\r\n]+\})/.exec(output);
      if (match) {
        clearTimeout(timer);
        resolve((JSON.parse(match[1] ?? "{}") as { url: string }).url);
      }
    });
    server.once("error", reject);
    server.once("exit", (code) => {
      clearTimeout(timer);
      reject(Error(`Storage backend exited ${code}`));
    });
  });
  const stub = await startFinoraStub({ stockOperationsServer: url });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const state = async () =>
    (await (await fetch(`${url}/__state__`)).json()) as {
      source: { quantity: number };
      cash: number;
      physical_value: number;
      report_inventory_value: number;
      in_transit_value: number;
      journals: number;
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
    await page.getByRole("button", { name: "المواقع والمخازن", exact: true }).click();
    await expect(page.getByRole("region", { name: "أرصدة المخزن الفرعي" })).toBeVisible();
    const before = await state();
    expect(before.source.quantity).toBe(6);
    expect(before.physical_value).toBe(1200);
    expect(before.report_inventory_value).toBe(1200);
    await page.getByRole("button", { name: "إضافة مخزن", exact: true }).click();
    await page.getByLabel("اسم المخزن", { exact: true }).fill("المخزن الخلفي");
    await page.getByLabel("رمز المخزن", { exact: true }).fill("BACK");
    await page.getByRole("button", { name: "حفظ المخزن", exact: true }).click();
    await expect(page.getByRole("complementary", { name: "إضافة مخزن", exact: true })).not.toBeVisible();
    await page.getByRole("button", { name: "نقل", exact: true }).click();
    await expect(page.getByRole("button", { name: "الأرصدة", exact: true })).toBeDisabled();
    await page.getByLabel("المخزن المقصود", { exact: true }).selectOption({ label: "المخزن الخلفي" });
    await page.getByLabel("كمية القطع", { exact: true }).fill("3");
    await page.getByLabel("سبب النقل", { exact: true }).fill("توزيع موثق داخل الفرع");
    await page.getByRole("button", { name: "حفظ المسودة", exact: true }).click();
    await expect(page.getByRole("button", { name: "إرسال القطع", exact: true })).toBeVisible();
    expect((await state()).source.quantity).toBe(6);
    await page.getByRole("button", { name: "إرسال القطع", exact: true }).click();
    expect((await state()).source.quantity).toBe(6);
    await page.getByRole("button", { name: "تأكيد العملية", exact: true }).click();
    await expect(page.getByRole("button", { name: "استلام القطع", exact: true })).toBeVisible();
    const sent = await state();
    expect(sent.source.quantity).toBe(3);
    expect(sent.in_transit_value).toBe(450);
    expect(sent.physical_value + sent.in_transit_value).toBe(1200);
    expect(sent.report_inventory_value).toBe(1200);
    expect(sent.cash).toBe(before.cash);
    await page.getByRole("button", { name: "استلام القطع", exact: true }).click();
    await page.getByRole("button", { name: "تأكيد العملية", exact: true }).click();
    await expect(page.getByRole("button", { name: "استلام القطع", exact: true })).not.toBeVisible();
    const received = await state();
    expect(received.source.quantity).toBe(6);
    expect(received.physical_value).toBe(1200);
    expect(received.report_inventory_value).toBe(1200);
    expect(received.in_transit_value).toBe(0);
    expect(received.cash).toBe(before.cash);
    expect(received.journals).toBe(before.journals);
    await page.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
    await page.getByRole("button", { name: "الأرصدة", exact: true }).click();
    const selector = page.getByLabel("المخزن الفرعي", { exact: true });
    const childValue = await selector
      .locator("option")
      .filter({ hasText: "المخزن الخلفي" })
      .getAttribute("value");
    if (!childValue) throw Error("The received storage site was not listed");
    await selector.selectOption(childValue);
    const region = page.getByRole("region", { name: "أرصدة المخزن الفرعي" });
    await expect(region.getByRole("cell", { name: "3", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "إخفاء", exact: true })).toHaveCount(0, { timeout: 10000 });
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setMinimumSize(900, 650));
    for (const width of [1536, 1180, 1024]) {
      await app.evaluate(({ BrowserWindow }, width) => {
        const win = BrowserWindow.getAllWindows()[0];
        win?.unmaximize();
        win?.setContentSize(width, 800);
      }, width);
      await expect.poll(() => page.evaluate(() => window.innerWidth)).toBe(width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(await region.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await page.screenshot({ path: path.join(outputs, `storage-${width}.png`), animations: "disabled" });
    }
    expect(errors).toEqual([]);
    writeFileSync(path.join(outputs, "verified-state.json"), JSON.stringify(received, null, 2));
  } catch (error) {
    const page = await app.firstWindow();
    console.log((await page.locator("body").innerText()).slice(-3000));
    await page.screenshot({ path: path.join(outputs, "failure.png") });
    throw error;
  } finally {
    await app.close();
    await stub.close();
    await fetch(`${url}/__shutdown__`).catch(() => undefined);
    if (server.exitCode === null) server.kill();
    rmSync(profile, { recursive: true, force: true });
  }
});
