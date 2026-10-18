import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("measured financial control separates capital, drawings and true cash gaps through real finance services", async () => {
  test.setTimeout(240000);
  const root = path.resolve(__dirname, "../../.."),
    outputs = path.join(root, "tests/_artifacts/financial-control-20261014");
  mkdirSync(outputs, { recursive: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-control-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-control-")
  )
    throw Error("Unsafe test cleanup");
  const installed = "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe";
  const server = spawn(
    process.env.FINORA_TEST_PYTHON ?? (existsSync(installed) ? installed : "python"),
    [path.join(root, "tests/desktop_cash_shift_server.py")],
    {
      cwd: root,
      windowsHide: true,
      env: {
        ...process.env,
        FINORA_CASH_SHIFT_UI_TEST: "1",
        FINORA_FINANCIAL_CONTROL_UI_TEST: "1",
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
      },
    },
  );
  let output = "",
    url = "";
  server.stderr.on("data", (chunk) => {
    output += String(chunk);
  });
  let app: Awaited<ReturnType<typeof electron.launch>> | undefined;
  let stub: Awaited<ReturnType<typeof startFinoraStub>> | undefined;
  try {
    url = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(Error(`Control server startup: ${output.slice(-2000)}`)), 60000);
      server.stdout.on("data", (chunk) => {
        output += String(chunk);
        const match = /CASH_SHIFT_TEST_READY (\{[^\r\n]+\})/.exec(output);
        if (match) {
          clearTimeout(timer);
          resolve((JSON.parse(match[1] ?? "{}") as { url: string }).url);
        }
      });
      server.once("error", (cause) => {
        clearTimeout(timer);
        reject(cause);
      });
      server.once("exit", (code) => {
        clearTimeout(timer);
        reject(Error(`Control server exit ${code}: ${output.slice(-2000)}`));
      });
    });
    stub = await startFinoraStub({ finance: true, cashShiftServer: url });
    app = await electron.launch({
      args: [path.resolve(__dirname, "..")],
      cwd: path.resolve(__dirname, ".."),
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
    const desktop = app,
      page = await desktop.firstWindow(),
      errors: string[] = [];
    page.on("pageerror", (cause) => errors.push(cause.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page.getByRole("dialog", { name: "المزيد" }).getByText("الحسابات", { exact: true }).click();
    const panel = page.getByRole("dialog", { name: "الحسابات", exact: true });
    await panel.getByRole("tab", { name: "الرقابة المالية", exact: true }).click();
    await expect(panel.getByRole("region", { name: "مصادر المركز المالي" })).toBeVisible();
    const state = async () =>
      (await (await fetch(`${url}/__state__`)).json()) as {
        cash: number;
        journals: number;
        snapshots: number;
      };
    const create = async (name: string, cash: string) => {
      const before = await state();
      await panel.getByRole("button", { name: "معاينة معدودة جديدة", exact: true }).click();
      await panel.getByLabel("اسم المعاينة", { exact: true }).fill(name);
      await panel.getByLabel("سبب المعاينة", { exact: true }).fill("مطابقة عد النقد وكشف البنك");
      await panel.getByLabel("النقد المعدود · الصندوق", { exact: true }).fill(cash);
      await panel.getByLabel("رصيد كشف الحساب · المصرف", { exact: true }).fill("0");
      await panel.getByLabel("دليل العد / الكشف · الصندوق", { exact: true }).fill("عد صندوق موثق");
      await panel.getByLabel("دليل العد / الكشف · المصرف", { exact: true }).fill("كشف رصيد البنك صفر");
      await panel.getByRole("button", { name: "حفظ المعاينة دون ترحيل", exact: true }).click();
      await expect(panel.getByRole("row").filter({ hasText: name })).toBeVisible();
      const after = await state();
      expect(after.cash).toBe(before.cash);
      expect(after.journals).toBe(before.journals);
      expect(after.snapshots).toBe(before.snapshots + 1);
      if (name === "قبل الحركات") {
        await panel.getByRole("button", { name: "طباعة المعاينة", exact: true }).click();
        await expect.poll(() => desktop.windows().length).toBe(2);
        const snapshotPrint = desktop.windows().find((window) => window !== page);
        if (!snapshotPrint) throw Error("No snapshot print window");
        await expect(snapshotPrint.getByText("عد صندوق موثق", { exact: true })).toBeVisible();
        const document = await desktop.evaluate(async ({ BrowserWindow }) => {
          const win = BrowserWindow.getAllWindows().find((item) =>
            item.webContents.getURL().includes("/accounts/finance/control/snapshots/1/print"),
          );
          if (!win) throw Error("No snapshot print window");
          return (await win.webContents.printToPDF({ printBackground: true, pageSize: "A4" })).toString(
            "base64",
          );
        });
        writeFileSync(path.join(outputs, "snapshot.pdf"), Buffer.from(document, "base64"));
        await snapshotPrint.close();
      }
      await panel.getByRole("button", { name: "إغلاق التفاصيل", exact: true }).click();
    };
    await create("قبل الحركات", "20000000");
    for (const action of ["capital", "draw", "expense"]) await fetch(`${url}/__${action}__`);
    await panel.getByRole("button", { name: "تحديث الرقابة", exact: true }).click();
    await create("بعد الحركات", "19980000");
    await panel.getByLabel("من معاينة", { exact: true }).fill("1");
    await panel.getByLabel("إلى معاينة", { exact: true }).fill("2");
    await panel.getByRole("button", { name: "مطابقة المعاينتين", exact: true }).click();
    await expect(panel.getByText("مطابقة موثقة", { exact: false }).first()).toBeVisible();
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ]) {
      await desktop.evaluate(
        ({ BrowserWindow }, size) => {
          const win = BrowserWindow.getAllWindows()[0];
          if (!win) throw Error("Missing main window");
          win.unmaximize();
          win.setMinimumSize(900, 650);
          win.setContentSize(size[0] ?? 1024, size[1] ?? 768);
        },
        [width, height],
      );
      await expect.poll(() => page.evaluate(() => innerWidth)).toBe(width);
      expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
      await page.screenshot({ path: path.join(outputs, `comparison-${width}.png`), animations: "disabled" });
    }
    await panel.getByRole("button", { name: "طباعة المطابقة", exact: true }).click();
    await expect.poll(() => desktop.windows().length).toBe(2);
    const print = desktop.windows().find((window) => window !== page);
    if (!print) throw Error("No control print window");
    await expect(print.getByRole("heading", { name: "مطابقة موثقة", exact: true })).toBeVisible();
    const pdf = await desktop.evaluate(async ({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) =>
        item.webContents.getURL().includes("/accounts/finance/control/compare/print"),
      );
      if (!win) throw Error("No comparison print window");
      return (await win.webContents.printToPDF({ printBackground: true, pageSize: "A4" })).toString("base64");
    });
    writeFileSync(path.join(outputs, "comparison.pdf"), Buffer.from(pdf, "base64"));
    await print.close();
    await create("فرق العد الفعلي", "19979500");
    await panel.getByLabel("من معاينة", { exact: true }).fill("2");
    await panel.getByLabel("إلى معاينة", { exact: true }).fill("3");
    await panel.getByRole("button", { name: "مطابقة المعاينتين", exact: true }).click();
    await expect(
      panel.getByText("توجد فروقات أو حدود قياس تحتاج مراجعة", { exact: false }).first(),
    ).toBeVisible();
    await expect(panel.getByText("-500 د.ع", { exact: true }).first()).toBeVisible();
    writeFileSync(
      path.join(outputs, "state.json"),
      JSON.stringify({ final: await state(), errors }, null, 2),
    );
    expect(errors).toEqual([]);
  } finally {
    await app?.close();
    await stub?.close();
    if (url)
      await fetch(`${url}/__shutdown__`).catch((cause) => {
        output += String(cause);
      });
    server.kill();
    writeFileSync(path.join(outputs, "backend.log"), output);
    rmSync(profile, { recursive: true, force: true });
  }
});
