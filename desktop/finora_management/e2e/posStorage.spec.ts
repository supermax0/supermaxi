import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";
test("cashier selects a real storage source, checks out, and posts its FIFO and cash once", async () => {
  test.setTimeout(180000);
  const root = path.resolve(__dirname, "../../.."),
    outputs = path.join(root, "tests/_artifacts/erp-pos-storage");
  mkdirSync(outputs, { recursive: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-pos-storage-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-pos-storage-")
  )
    throw Error("Unsafe test cleanup");
  const installed = "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe";
  const server = spawn(
    process.env.FINORA_TEST_PYTHON ?? (existsSync(installed) ? installed : "python"),
    [path.join(root, "tests/_artifacts/erp-regression/pos_storage_electron_server.py")],
    {
      cwd: root,
      windowsHide: true,
      env: {
        ...process.env,
        FINORA_POS_STORAGE_UI_TEST: "1",
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
      },
    },
  );
  let output = "";
  const url = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => reject(Error("POS storage backend did not start")), 60000);
    server.stdout.on("data", (chunk) => {
      output += String(chunk);
      const match = /POS_STORAGE_READY (\{[^\r\n]+\})/.exec(output);
      if (match) {
        clearTimeout(timer);
        resolve((JSON.parse(match[1] ?? "{}") as { url: string }).url);
      }
    });
    server.once("error", reject);
    server.once("exit", (code) => {
      clearTimeout(timer);
      reject(Error(`POS backend exited ${code}`));
    });
  });
  const stub = await startFinoraStub({ posStorageServer: url });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const state = async () =>
    (await (await fetch(`${url}/__state__`)).json()) as {
      main: number;
      child: number;
      cash: number;
      layers: number[][];
      sources: (number | null)[];
    };
  try {
    const page = await app.firstWindow();
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "نقطة البيع", exact: true }).first().click();
    const pos = page.getByRole("dialog", { name: "نقطة البيع" });
    await pos.getByRole("button", { name: "إضافة صنف نقل", exact: true }).click();
    await pos.getByLabel("كمية صنف نقل").fill("2");
    await pos.getByLabel("مصدر صنف نقل", { exact: true }).selectOption({ label: "المخزن الخلفي" });
    await pos.getByLabel("البحث عن زبون").fill("مصدر");
    await page.getByRole("button", { name: /عميل مصدر الكاشير/ }).click();
    const before = await state();
    expect(before.main).toBe(3);
    expect(before.child).toBe(3);
    await pos.getByRole("button", { name: "خيارات التنفيذ", exact: true }).click();
    await page.getByRole("menuitem", { name: "تنفيذ بدون طباعة", exact: true }).click();
    await expect(page.getByText(/تم تنفيذ الطلب #/)).toBeVisible();
    const after = await state();
    expect(after.main).toBe(3);
    expect(after.child).toBe(1);
    expect(after.layers).toEqual([[2, 100]]);
    expect(after.cash - before.cash).toBe(800);
    expect(after.sources[0]).toBeGreaterThan(0);
    expect(stub.bodies.filter((row) => row.path === "/pos/create-order")).toHaveLength(1);
    await page.screenshot({ path: path.join(outputs, "cashier-source.png"), animations: "disabled" });
    writeFileSync(path.join(outputs, "verified-state.json"), JSON.stringify(after, null, 2));
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
