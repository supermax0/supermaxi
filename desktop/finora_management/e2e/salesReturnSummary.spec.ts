import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

for (const undated of [false, true]) {
  test(`real ${undated ? "undated" : "dated"} partial-return evidence stays clear without changing money or stock`, async () => {
    test.setTimeout(240000);
    const root = path.resolve(__dirname, "../../..");
    const outputs = path.join(root, "tests/_artifacts/sales-returns-20261014");
    mkdirSync(outputs, { recursive: true });
    const profile = mkdtempSync(path.join(tmpdir(), "finora-return-summary-"));
    if (
      path.dirname(profile) !== path.resolve(tmpdir()) ||
      !path.basename(profile).startsWith("finora-return-summary-")
    )
      throw Error("Unsafe test cleanup");
    const installed = "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe";
    const server = spawn(
      process.env.FINORA_TEST_PYTHON ?? (existsSync(installed) ? installed : "python"),
      [path.join(root, "tests/desktop_sales_return_server.py")],
      {
        cwd: root,
        windowsHide: true,
        env: {
          ...process.env,
          FINORA_RETURN_SUMMARY_UI_TEST: "1",
          FINORA_UNDATED_RETURN_UI_TEST: undated ? "1" : "0",
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
      const setup = await new Promise<{ url: string; orderId: number }>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(Error(`Return backend startup: ${output.slice(-2000)}`)),
          60000,
        );
        server.stdout.on("data", (chunk) => {
          output += String(chunk);
          const match = /RETURN_SUMMARY_TEST_READY (\{[^\r\n]+\})/.exec(output);
          if (match) {
            clearTimeout(timer);
            resolve(JSON.parse(match[1] ?? "{}") as { url: string; orderId: number });
          }
        });
        server.once("error", (error) => {
          clearTimeout(timer);
          reject(error);
        });
        server.once("exit", (code) => {
          clearTimeout(timer);
          reject(Error(`Return backend exited ${code}: ${output.slice(-2000)}`));
        });
      });
      url = setup.url;
      const state = async () => (await (await fetch(`${url}/__state__`)).json()) as Record<string, number>;
      const before = await state();
      expect(before).toMatchObject({
        cash: 20000000,
        bank: undated ? 0 : 400,
        default_cash: undated ? 400 : 0,
        undated_collection: undated ? 800 : 0,
        inventory: 1100,
        documents: 1,
        total: 400,
        paid: 400,
      });
      stub = await startFinoraStub({ orderLifecycleServer: url });
      app = await electron.launch({
        args: [path.resolve(__dirname, "..")],
        cwd: path.resolve(__dirname, ".."),
        env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
      });
      const desktop = app,
        page = await desktop.firstWindow(),
        errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
      await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
      await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
      await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
      await page
        .getByRole("navigation", { name: "النوافذ" })
        .getByRole("button", { name: "الطلبات", exact: true })
        .click();
      await page.getByRole("button", { name: `إجراءات الطلب ${setup.orderId}` }).click();
      await page.getByRole("menuitem", { name: "عرض التفاصيل" }).click();
      const drawer = page.getByRole("complementary", { name: `الطلب #${setup.orderId}` });
      const summary = drawer.getByRole("region", { name: "تسوية المرتجعات" });
      await expect(summary).toContainText("أصل البيع");
      await expect(summary).toContainText("800");
      await expect(summary).toContainText("400");
      if (undated) {
        await expect(summary).toContainText("تحصيل قديم غير مؤرخ");
        await expect(summary).toContainText("لم يُسجّل كقبض جديد");
      } else {
        await expect(summary).not.toContainText("تحصيل قديم غير مؤرخ");
      }
      await expect(drawer.getByText("راجع: 1 · المتبقي: 1", { exact: true })).toBeVisible();
      await expect(drawer.getByRole("button", { name: "تعديل سريع", exact: true })).toHaveCount(0);
      for (const width of [1536, 1180, 1024]) {
        await desktop.evaluate(({ BrowserWindow }, size) => {
          const win = BrowserWindow.getAllWindows()[0];
          win?.unmaximize();
          win?.setMinimumSize(900, 700);
          win?.setContentSize(size, 850);
        }, width);
        await expect.poll(() => page.evaluate(() => window.innerWidth)).toBe(width);
        await summary.scrollIntoViewIfNeeded();
        await expect(summary).toBeVisible();
        await page.screenshot({
          path: path.join(outputs, `desktop-${undated ? "undated" : "partial"}-${width}.png`),
        });
      }
      expect(errors).toEqual([]);
      const after = await state();
      expect(after).toEqual(before);
      writeFileSync(
        path.join(
          outputs,
          undated ? "desktop-undated-verification.json" : "desktop-summary-verification.json",
        ),
        JSON.stringify({ before, after, widths: [1536, 1180, 1024] }, null, 2),
      );
    } finally {
      await app?.close();
      await stub?.close();
      if (url) await fetch(`${url}/__shutdown__`).catch(() => undefined);
      if (server.exitCode === null)
        await new Promise<void>((resolve) => {
          const timer = setTimeout(() => {
            server.kill();
            resolve();
          }, 5000);
          server.once("exit", () => {
            clearTimeout(timer);
            resolve();
          });
        });
      rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    }
  });
}
