import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { closeIsolatedApp } from "./closeIsolatedApp";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

function removeProfile(directory: string) {
  if (
    path.dirname(path.resolve(directory)) !== path.resolve(os.tmpdir()) ||
    !path.basename(directory).startsWith("finora-workspace-")
  )
    throw Error("Unsafe cleanup");
  rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}

test("native Smart Workspace layout, real navigation, preferences and read-only assistant", async () => {
  test.setTimeout(180_000);
  const stub = await startFinoraStub({ workspace: true, finance: true, customers: true, hr: true });
  const directory = mkdtempSync(path.join(os.tmpdir(), "finora-workspace-"));
  const artifacts = path.resolve(
    `../../.codex-tmp/${process.env.FINORA_E2E_EXECUTABLE ? "workspace-preview-packaged" : "workspace-preview"}`,
  );
  mkdirSync(artifacts, { recursive: true });
  const app = await electron.launch({
    ...(process.env.FINORA_E2E_EXECUTABLE ? { executablePath: process.env.FINORA_E2E_EXECUTABLE } : {}),
    args: process.env.FINORA_E2E_EXECUTABLE ? [] : [path.resolve(__dirname, "..")],
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: directory },
  });
  let failed = false;
  try {
    expect(await app.evaluate(({ app }) => app.getPath("userData"))).toBe(directory);
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم", { exact: true }).fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور", { exact: true }).fill(STUB_CREDENTIALS.password);
    const started = Date.now();
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    const home = page.getByRole("main", { name: "الرئيسية" });
    await expect(home.getByRole("region", { name: "مبيعات اليوم" }).locator("strong")).toContainText(
      "4,850,000",
    );
    await expect(home.getByRole("region", { name: "المستحقات" }).locator("strong")).toContainText(
      "2,450,000",
    );
    await page.screenshot({ path: path.join(artifacts, "workspace-initial.png") });
    const loadedMs = Date.now() - started;
    expect(loadedMs).toBeLessThan(15_000);
    await home.getByRole("button", { name: /طلبات بانتظار التجهيز/ }).click();
    const orders = page.getByRole("dialog", { name: "إدارة الطلبات", exact: true });
    await expect(orders).toBeVisible();
    await expect(orders.getByRole("tab", { name: /تم الطلب/ })).toHaveAttribute("aria-selected", "true");
    await orders.getByRole("button", { name: "إغلاق النافذة", exact: true }).click();
    await expect(home).toBeVisible();
    await home.getByRole("button", { name: "منتج جديد", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "منتج جديد", exact: true })).toBeVisible();
    await page
      .getByRole("dialog", { name: "منتج جديد", exact: true })
      .getByRole("button", { name: /إغلاق|إلغاء/ })
      .first()
      .click();
    await page
      .getByRole("dialog", { name: "إدارة المنتجات", exact: true })
      .getByRole("button", { name: "إغلاق النافذة", exact: true })
      .click();
    await home.getByRole("button", { name: "سند قبض", exact: true }).click();
    const finance = page.getByRole("dialog", { name: "الحسابات", exact: true });
    await expect(finance).toBeVisible();
    await expect(finance.getByRole("combobox", { name: "سبب العملية" })).toHaveValue("customer_payment");
    await page.keyboard.press("Escape");
    await finance.getByRole("button", { name: "إغلاق النافذة", exact: true }).click();
    await home.getByRole("button", { name: "تخصيص مساحة العمل", exact: true }).click();
    const customization = page.getByRole("dialog", { name: "تخصيص مساحة العمل" });
    await customization.getByRole("button", { name: "مضغوط", exact: true }).click();
    await customization.getByRole("button", { name: "حفظ التخصيص", exact: true }).click();
    await expect(home).toHaveClass(/workspace-compact/);
    await page.reload();
    await expect(home).toHaveClass(/workspace-compact/);
    await home.getByRole("button", { name: "عرض كل المهام", exact: true }).click();
    const tasks = page.getByRole("dialog", { name: "مركز المتابعة", exact: true });
    await expect(tasks.locator(".workspace-list-row")).toHaveCount(5);
    await expect(tasks.getByRole("button", { name: /طلب تصحيح دوام ينتظر الموافقة/ })).toBeVisible();
    await tasks.getByRole("button", { name: "إغلاق", exact: true }).click();
    const measurements: unknown[] = [];
    for (const density of ["مضغوط", "مريح"]) {
      await home.getByRole("button", { name: "تخصيص مساحة العمل", exact: true }).click();
      await customization.getByRole("button", { name: density, exact: true }).click();
      await customization.getByRole("button", { name: "حفظ التخصيص", exact: true }).click();
      await expect(page.getByText("تم حفظ مساحة العمل", { exact: true })).toBeHidden({ timeout: 7_000 });
      for (const [width, height, zoom] of [
        [1366, 768, 1],
        [1440, 900, 1],
        [1600, 900, 1],
        [1920, 1080, 1],
        [1920, 1080, 1.25],
        [1920, 1080, 1.5],
        [1440, 900, 1.25],
        [2560, 1440, 1.5],
        [1024, 768, 1],
        [760, 600, 1],
      ]) {
        await app.evaluate(
          ({ BrowserWindow }, size) => {
            const window = BrowserWindow.getAllWindows()[0];
            window?.setSize(size[0] ?? 1366, size[1] ?? 768);
            window?.webContents.setZoomFactor(size[2] ?? 1);
          },
          [width, height, zoom],
        );
        await page.waitForTimeout(200);
        const size = await home.evaluate((node) => {
          const viewport = node.parentElement;
          const bottom = node.querySelector(".workspace-bottom");
          if (!viewport || !bottom) throw Error("Workspace layout is incomplete");
          return {
            client: node.clientWidth,
            scroll: node.scrollWidth,
            height: node.clientHeight,
            scrollHeight: node.scrollHeight,
            viewportWidth: viewport.clientWidth,
            panels: Array.from(
              node.querySelectorAll(
                ".workspace-panels .workspace-panel-body, .workspace-bottom .workspace-panel-body",
              ),
            ).map((panel) => ({
              client: panel.clientHeight,
              scroll: panel.scrollHeight,
            })),
            bottom: bottom.getBoundingClientRect().bottom,
            visibleBottom: node.getBoundingClientRect().bottom,
            cards: Array.from(node.querySelectorAll(".workspace-kpis > div")).map((card) => ({
              x: card.getBoundingClientRect().x,
              y: card.getBoundingClientRect().y,
              w: card.getBoundingClientRect().width,
              h: card.getBoundingClientRect().height,
            })),
          };
        });
        expect(size.scroll).toBeLessThanOrEqual(size.client + 1);
        if (size.viewportWidth >= 960 && size.height >= 560) {
          expect(
            size.scrollHeight,
            JSON.stringify({ width, height, zoom, density, size }),
          ).toBeLessThanOrEqual(size.height + 1);
          expect(size.bottom).toBeLessThanOrEqual(size.visibleBottom + 1);
        }
        if (size.viewportWidth >= 1100 && size.height >= 640) {
          expect(size.panels).toHaveLength(5);
          for (const panel of size.panels) {
            if (!panel) throw Error("Quick actions or assistant panel missing");
            expect(panel.scroll, JSON.stringify({ width, height, zoom, density, panel })).toBeLessThanOrEqual(
              panel.client + 1,
            );
          }
        }
        expect(
          Math.max(...size.cards.map((card) => card.h)) - Math.min(...size.cards.map((card) => card.h)),
        ).toBeLessThan(2);
        await home.evaluate((node) => {
          node.scrollTop = 0;
        });
        const capture = await app.evaluate(async ({ BrowserWindow }) => {
          const window = BrowserWindow.getAllWindows()[0];
          if (!window) throw Error("Test window closed before screenshot");
          return (await window.capturePage()).toPNG().toString("base64");
        });
        writeFileSync(
          path.join(
            artifacts,
            `workspace-${width}x${height}-${zoom}-${density === "مريح" ? "comfortable" : "compact"}.png`,
          ),
          Buffer.from(capture, "base64"),
        );
        measurements.push({ windowWidth: width, windowHeight: height, zoom, density, ...size });
      }
    }
    await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0];
      window?.webContents.setZoomFactor(1);
      window?.setSize(1366, 768);
    });
    const hiddenWidgets = ["الطلبات", "المتابعة", "المستحقات", "يحتاج اهتمامك", "أكمل من حيث توقفت"];
    await home.getByRole("button", { name: "تخصيص مساحة العمل", exact: true }).click();
    for (const label of hiddenWidgets)
      await customization.getByRole("checkbox", { name: label, exact: true }).uncheck();
    await customization.getByRole("button", { name: "حفظ التخصيص", exact: true }).click();
    for (const selector of [".workspace-kpis", ".workspace-panels"]) {
      const row = home.locator(selector);
      await expect(row.locator(":scope > div")).toHaveCount(1);
      const unused = await row.evaluate((node) => {
        if (!node.firstElementChild) throw Error("Customized workspace card missing");
        return node.getBoundingClientRect().width - node.firstElementChild.getBoundingClientRect().width;
      });
      expect(unused).toBeLessThanOrEqual(1);
    }
    await home.getByRole("button", { name: "تخصيص مساحة العمل", exact: true }).click();
    for (const label of hiddenWidgets)
      await customization.getByRole("checkbox", { name: label, exact: true }).check();
    await customization.getByRole("button", { name: "حفظ التخصيص", exact: true }).click();
    await home.getByLabel("اسأل FINORA").fill("اعرض طلبات اليوم");
    await home.getByRole("button", { name: "إرسال إلى مساعد FINORA", exact: true }).click();
    const assistant = page.getByRole("complementary", { name: "مساعد فينورا", exact: true });
    await expect(assistant).toBeVisible();
    await expect(assistant.getByLabel("سؤال مساعد فينورا")).toHaveValue("اعرض طلبات اليوم");
    await assistant.getByRole("button", { name: "إرسال سؤال المساعد", exact: true }).click();
    await expect(assistant.getByText(/تقدر تبدأ بالتعليم التفاعلي/)).toBeVisible();
    expect(await home.evaluate((node) => node.scrollHeight - node.clientHeight)).toBeLessThanOrEqual(1);
    expect(stub.bodies.filter((row) => row.path === "/finora-ai/api/desktop/chat")).toHaveLength(0);
    expect(stub.bodies.some((row) => /commands|checkout|payment$/.test(row.path))).toBe(false);
    expect(errors).toEqual([]);
    writeFileSync(
      path.join(artifacts, "measurements.json"),
      JSON.stringify(
        {
          loadedMs,
          runtime: await app.evaluate(() => ({ electron: process.versions.electron, arch: process.arch })),
          measurements,
          errors,
        },
        null,
        2,
      ),
    );
  } catch (error) {
    failed = true;
    writeFileSync(
      path.join(artifacts, "failure.json"),
      JSON.stringify(
        {
          error: String(error),
          profile: directory,
          pid: app.process().pid,
          exitCode: app.process().exitCode,
          signalCode: app.process().signalCode,
        },
        null,
        2,
      ),
    );
    throw error;
  } finally {
    await cleanup(app, stub.close, directory, failed);
  }
});

async function cleanup(
  app: Awaited<ReturnType<typeof electron.launch>>,
  closeStub: () => Promise<void>,
  directory: string,
  failed: boolean,
) {
  try {
    if (app.process().exitCode === null) await closeIsolatedApp(app);
  } catch (error) {
    if (!failed) throw error;
    console.error(
      "Test process already closed; original failure and isolated profile retained.",
      String(error),
    );
  }
  await closeStub();
  if (!failed) removeProfile(directory);
}
