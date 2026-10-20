import { mkdtempSync, rmSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { FinoraDesktopBridge } from "../shared/ipc";
import { closeIsolatedApp } from "./closeIsolatedApp";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeProfile(directory: string) {
  if (
    path.dirname(path.resolve(directory)) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-desktop-safety-")
  )
    throw Error("Unsafe cleanup");
  rmSync(directory, { recursive: true, force: true });
}

test("native workspace without connected pages, safe exit and encrypted backup restore", async () => {
  test.setTimeout(120_000);
  const stub = await startFinoraStub();
  const directory = mkdtempSync(path.join(os.tmpdir(), "finora-desktop-safety-"));
  const app = await electron.launch({
    ...(process.env.FINORA_E2E_EXECUTABLE ? { executablePath: process.env.FINORA_E2E_EXECUTABLE } : {}),
    args: process.env.FINORA_E2E_EXECUTABLE ? [] : [path.resolve(__dirname, "..")],
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: directory },
  });
  try {
    expect(await app.evaluate(({ app }) => app.getPath("userData"))).toBe(directory);
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم", { exact: true }).fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور", { exact: true }).fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await expect(page.getByRole("main", { name: "الرئيسية" })).toBeVisible();
    for (const [width, height] of [
      [1440, 900],
      [1024, 600],
      [760, 480],
    ]) {
      await app.evaluate(
        ({ BrowserWindow }, size) => {
          BrowserWindow.getAllWindows()[0]?.setSize(size[0] ?? 760, size[1] ?? 480);
        },
        [width, height],
      );
      await page.waitForTimeout(250);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await expect(page.getByRole("button", { name: "الإعدادات", exact: true })).toBeInViewport();
      await page.screenshot({ path: path.join(directory, `shell-${width}.png`) });
    }
    await page.getByRole("button", { name: "الإعدادات", exact: true }).click();
    await page.getByRole("button", { name: "النسخ والاستعادة", exact: true }).click();
    await page.getByRole("button", { name: "حفظ نسخة مشفّرة" }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "حفظ نسخة مشفّرة" })).toBeInViewport();
    await page.getByRole("button", { name: "إغلاق الإعدادات" }).click();
    expect(
      await page.evaluate(
        () => "pages" in ((window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop ?? {}),
      ),
    ).toBe(false);
    expect(stub.requests.some((request) => request === "GET /api/v1/desktop/workspace")).toBe(false);
    await app.evaluate(({ dialog }) => {
      dialog.showMessageBoxSync = () => 0;
      dialog.showMessageBox = async () => ({ response: 0, checkboxChecked: false });
    });
    await page.evaluate(() =>
      (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.lifecycle?.activity({
        dirty: false,
        saving: true,
      }),
    );
    expect(
      await page.evaluate(() =>
        (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.lifecycle?.confirmLeave(),
      ),
    ).toBe(false);
    await page.evaluate(() =>
      (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.lifecycle?.activity({
        dirty: false,
        saving: false,
      }),
    );
    const backupFile = path.join(directory, "saved.finorabackup");
    await app.evaluate(({ dialog }, file) => {
      dialog.showSaveDialog = async () => ({ canceled: false, filePath: file });
    }, backupFile);
    const exported = await page.evaluate(() =>
      (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.backup?.export(
        "test backup password",
      ),
    );
    expect(exported).toEqual({ saved: true });
    await app.evaluate(({ dialog }, file) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] });
      dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false });
    }, backupFile);
    await expect(
      page.evaluate(() =>
        (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.backup?.restore(
          "wrong password value",
        ),
      ),
    ).rejects.toThrow();
    const restored = await page.evaluate(() =>
      (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.backup?.restore(
        "test backup password",
      ),
    );
    expect(restored).toEqual({ restored: true });
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await expect(page.getByRole("main", { name: "الرئيسية" })).toBeVisible();
    expect(errors).toEqual([]);
    // Keep screenshots as explicit local QA artifacts, independent of the test profile.
    const { copyFileSync, mkdirSync } = await import("node:fs");
    const artifacts = path.resolve(__dirname, "../../../.codex-tmp/desktop-0.8.1-layout");
    mkdirSync(artifacts, { recursive: true });
    for (const width of [1440, 1024, 760])
      copyFileSync(path.join(directory, `shell-${width}.png`), path.join(artifacts, `shell-${width}.png`));
  } finally {
    await app.evaluate(({ BrowserWindow }) => {
      for (const win of BrowserWindow.getAllWindows()) win.destroy();
    });
    await app.close();
    await stub.close();
    removeProfile(directory);
  }
});

test("recovers a missing Windows key into a new slot while preserving the original encrypted database", async () => {
  const stub = await startFinoraStub();
  const directory = mkdtempSync(path.join(os.tmpdir(), "finora-desktop-safety-"));
  const launch = () =>
    electron.launch({
      ...(process.env.FINORA_E2E_EXECUTABLE ? { executablePath: process.env.FINORA_E2E_EXECUTABLE } : {}),
      args: process.env.FINORA_E2E_EXECUTABLE ? [] : [path.resolve(__dirname, "..")],
      env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: directory },
    });
  let application = await launch();
  try {
    const page = await application.firstWindow();
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم", { exact: true }).fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور", { exact: true }).fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await expect(page.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await expect(page.getByRole("main", { name: "الرئيسية" })).toBeVisible();
    const file = path.join(directory, "recover.finorabackup");
    await application.evaluate(({ dialog }, file) => {
      dialog.showSaveDialog = async () => ({ canceled: false, filePath: file });
    }, file);
    expect(
      await page.evaluate(() =>
        (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.backup?.export(
          "test backup password",
        ),
      ),
    ).toEqual({ saved: true });
    await closeIsolatedApp(application);
    const originalFile = path.join(directory, "offline", "business.sqlite.enc");
    const original = readFileSync(originalFile);
    writeFileSync(path.join(directory, "offline", "key.dpapi"), "invalid test DPAPI key");
    application = await launch();
    const recovered = await application.firstWindow();
    await expect(recovered.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    const status = await recovered.evaluate(() =>
      (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.offline?.status(),
    );
    expect(status?.available).toBe(false);
    await application.evaluate(({ dialog }, file) => {
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] });
      dialog.showMessageBox = async () => ({ response: 1, checkboxChecked: false });
    }, file);
    expect(
      await recovered.evaluate(() =>
        (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.backup?.restore(
          "test backup password",
        ),
      ),
    ).toEqual({ restored: true });
    await expect(recovered.getByRole("navigation", { name: "النوافذ" })).toBeVisible();
    await expect
      .poll(
        async () =>
          (
            await recovered.evaluate(() =>
              (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.offline?.status(),
            )
          )?.available,
      )
      .toBe(true);
    expect(readFileSync(originalFile)).toEqual(original);
    const slot = JSON.parse(readFileSync(path.join(directory, "offline", "current.json"), "utf8")) as {
      file: string;
      key: string;
    };
    expect(existsSync(path.join(directory, "offline", slot.file))).toBe(true);
    expect(existsSync(path.join(directory, "offline", slot.key))).toBe(true);
  } finally {
    await application.evaluate(({ BrowserWindow }) => {
      for (const win of BrowserWindow.getAllWindows()) win.destroy();
    });
    await application.close();
    await stub.close();
    removeProfile(directory);
  }
});
