import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("cash shifts reconcile real posted expenses and freeze closing evidence in Electron", async () => {
  test.setTimeout(240000);
  const root = path.resolve(__dirname, "../../..");
  const outputs = path.join(root, "tests/_artifacts/erp-cash-shifts-20261014");
  mkdirSync(outputs, { recursive: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-cash-shifts-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-cash-shifts-")
  )
    throw Error("Unsafe test cleanup");
  const installed = "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe";
  const server = spawn(
    process.env.FINORA_TEST_PYTHON ?? (existsSync(installed) ? installed : "python"),
    [path.join(root, "tests/desktop_cash_shift_server.py")],
    {
      cwd: root,
      env: {
        ...process.env,
        FINORA_CASH_SHIFT_UI_TEST: "1",
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
      },
      windowsHide: true,
    },
  );
  let output = "";
  server.stderr.on("data", (chunk) => {
    output += String(chunk);
  });
  let stub: Awaited<ReturnType<typeof startFinoraStub>> | undefined;
  let app: Awaited<ReturnType<typeof electron.launch>> | undefined;
  let url = "";
  try {
    url = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(Error(`Cash shift backend did not start: ${output.slice(-2000)}`)),
        60000,
      );
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
        reject(Error(`Cash shift backend exited ${code}: ${output.slice(-2000)}`));
      });
    });
    stub = await startFinoraStub({ finance: true, cashShiftServer: url });
    app = await electron.launch({
      args: [path.resolve(__dirname, "..")],
      cwd: path.resolve(__dirname, ".."),
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
    });
    const desktop = app;
    const page = await desktop.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (cause) => errors.push(cause.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page.getByRole("dialog", { name: "المزيد" }).getByText("الحسابات", { exact: true }).click();
    const panel = page.getByRole("dialog", { name: "الحسابات", exact: true });
    await panel.getByRole("tab", { name: "ورديات الصندوق", exact: true }).click();
    await panel.getByRole("button", { name: "فتح وردية", exact: true }).click();
    await panel.getByLabel("اسم الوردية").fill("مسائية مالية");
    await panel.getByLabel("النقد الفعلي عند الافتتاح").fill("20000000");
    await panel.getByRole("button", { name: "تأكيد افتتاح الوردية", exact: true }).click();
    await expect(panel.getByRole("row").filter({ hasText: "مسائية مالية" })).toBeVisible();
    const before = (await (await fetch(`${url}/__state__`)).json()) as {
      cash: number;
      journals: number;
      shifts: number;
      closed: number;
    };
    expect(before.shifts).toBe(1);
    await fetch(`${url}/__expense__`);
    await panel.getByRole("button", { name: "تحديث الورديات", exact: true }).click();
    await expect(panel.getByText("19,900,000", { exact: true })).toBeVisible();
    await panel.getByLabel("النقد المعدود عند الإقفال").fill("19899500");
    await panel.getByRole("button", { name: "تأكيد إغلاق الوردية", exact: true }).click();
    await expect(panel.getByRole("alert").filter({ hasText: "سبب العجز" })).toBeVisible();
    await panel.getByLabel("سبب الفرق / الملاحظات").fill("عجز عد فعلي 500 دينار");
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ]) {
      await desktop.evaluate(
        ({ BrowserWindow }, size) => {
          const window = BrowserWindow.getAllWindows()[0];
          if (!window) throw Error("Missing main window");
          window.unmaximize();
          window.setMinimumSize(900, 650);
          window.setContentSize(size[0] ?? 1536, size[1] ?? 900);
        },
        [width, height],
      );
      await expect.poll(() => page.evaluate(() => window.innerWidth)).toBe(width);
      await expect.poll(() => page.evaluate(() => window.innerHeight)).toBe(height);
      const confirm = panel.getByRole("button", { name: "تأكيد إغلاق الوردية", exact: true });
      await expect(confirm).toBeVisible();
      const bounds = await confirm.boundingBox();
      if (!bounds) throw Error("Closing action has no visible bounds");
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(height ?? 768);
      const amount = panel.getByText("19,900,000", { exact: true });
      await amount.scrollIntoViewIfNeeded();
      expect(await amount.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await page.screenshot({ path: path.join(outputs, `closing-${width}.png`) });
      expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    }
    const counted = (await (await fetch(`${url}/__state__`)).json()) as typeof before;
    await panel.getByRole("button", { name: "تأكيد إغلاق الوردية", exact: true }).click();
    await expect(
      panel.getByRole("row").filter({ hasText: "مسائية مالية" }).getByText("مغلقة", { exact: true }),
    ).toBeVisible();
    const after = (await (await fetch(`${url}/__state__`)).json()) as typeof before;
    expect(after.cash).toBe(counted.cash);
    expect(after.journals).toBe(counted.journals);
    expect(after.closed).toBe(1);
    await panel.getByRole("button", { name: "طباعة كشف الوردية", exact: true }).click();
    await expect.poll(() => desktop.windows().length).toBe(2);
    const print = desktop.windows().find((window) => window !== page);
    if (!print) throw Error("Missing cash shift print window");
    await expect(print.getByText("مغلقة — أرقام محفوظة وقت الإقفال")).toBeVisible();
    await print.screenshot({ path: path.join(outputs, "closing-print.png") });
    const pdf = await desktop.evaluate(async ({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) =>
        item.webContents.getURL().includes("/accounts/finance/cash-shifts/"),
      );
      if (!win) throw Error("Missing cash shift print window");
      return (await win.webContents.printToPDF({ printBackground: true, pageSize: "A4" })).toString("base64");
    });
    writeFileSync(path.join(outputs, "closing.pdf"), Buffer.from(pdf, "base64"));
    writeFileSync(
      path.join(outputs, "state.json"),
      JSON.stringify({ before, counted, after, errors }, null, 2),
    );
    expect(errors).toEqual([]);
  } finally {
    await app?.close();
    await stub?.close();
    if (url)
      await fetch(`${url}/__shutdown__`).catch((cause) => {
        output += `Shutdown: ${String(cause)}`;
      });
    server.kill();
    writeFileSync(path.join(outputs, "backend.log"), output);
    rmSync(profile, { recursive: true, force: true });
  }
});
