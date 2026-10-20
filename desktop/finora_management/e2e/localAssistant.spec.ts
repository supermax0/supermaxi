import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import os from "node:os";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";
import { closeIsolatedApp } from "./closeIsolatedApp";
import type { FinoraDesktopBridge } from "../shared/ipc";

test("local assistant settings, two real HTTP protocols, teaching, scoped search and reviewed drafts", async () => {
  test.setTimeout(180000);
  const stub = await startFinoraStub({ workspace: true, finance: true, customers: true, hr: true });
  const calls: Array<{ url: string; payload: Record<string, unknown> }> = [];
  const model = createServer((req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.url === "/api/tags") {
      res.end(JSON.stringify({ models: [{ name: "finora-test-local" }] }));
      return;
    }
    if (req.url === "/v1/models") {
      res.end(JSON.stringify({ data: [{ id: "finora-test-local" }] }));
      return;
    }
    let body = "";
    req.on("data", (c) => (body += String(c)));
    req.on("end", () => {
      const payload = JSON.parse(body) as Record<string, unknown>;
      calls.push({ url: req.url ?? "", payload });
      const messages = payload.messages as Array<{ role: string; content: string }>;
      const question = messages.filter((m) => m.role === "user").at(-1)?.content ?? "";
      const hasResult = messages.some((m) => m.role === "tool");
      let message: Record<string, unknown> = {
        role: "assistant",
        content: question.includes("طويل")
          ? "شرح محلي طويل. ".repeat(1200)
          : hasResult
            ? "تمت القراءة من أدوات فينورا، راجع المصدر والمقترح أدناه."
            : "جاهز محلياً",
      };
      if (!hasResult && (question.includes("رصيد") || question.includes("جهز"))) {
        const name = question.includes("رصيد") ? "get_customer_balance" : "finora_prepare",
          args =
            name === "get_customer_balance"
              ? { customer_id: 1 }
              : {
                  kind: "product",
                  title: "منتج مقترح للمراجعة",
                  fields: { name: "منتج من المساعد", salePrice: 15000 },
                };
        message = {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              ...(req.url === "/v1/chat/completions" ? { id: "local-test-call", type: "function" } : {}),
              function: { name, arguments: req.url === "/api/chat" ? args : JSON.stringify(args) },
            },
          ],
        };
      }
      res.end(
        JSON.stringify(
          req.url === "/api/chat"
            ? { message, prompt_eval_count: 100, eval_count: 30 }
            : { choices: [{ message }], usage: { prompt_tokens: 100, completion_tokens: 30 } },
        ),
      );
    });
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const port = (model.address() as AddressInfo).port;
  const directory = mkdtempSync(path.join(os.tmpdir(), "finora-local-ai-"));
  const artifacts = path.resolve(
    `../../.codex-tmp/assistant-release/${process.env.FINORA_ASSISTANT_VARIANT ?? "development"}`,
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
    const page = await app.firstWindow(),
      errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم", { exact: true }).fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور", { exact: true }).fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    const home = page.getByRole("main", { name: "الرئيسية" });
    await expect(home).toBeVisible();
    await page.getByLabel("فتح مساعد فينورا", { exact: true }).click();
    const panel = page.getByRole("complementary", { name: "مساعد فينورا", exact: true });
    await panel.getByRole("button", { name: "علّمني", exact: true }).click();
    await panel.getByRole("button", { name: "علّمني خطوة بخطوة" }).first().click();
    const training = page.getByRole("region", { name: "التعليم التفاعلي" });
    await expect(training).toBeVisible();
    await training.getByLabel("إيقاف التعليم").click();
    await page.getByLabel("فتح مساعد فينورا", { exact: true }).click();
    await panel.getByLabel("إعدادات المساعد المحلي").click();
    const settings = page.getByRole("dialog", { name: "الإعدادات", exact: true });
    await expect(settings.getByText("التفعيل خطوة بخطوة", { exact: true })).toBeVisible();
    await settings.getByLabel("منفذ الذكاء المحلي").fill(String(port));
    await settings.getByRole("button", { name: "فحص الاتصال وجلب النماذج" }).click();
    await expect(settings.getByLabel("معرف النموذج المحلي")).toHaveValue("finora-test-local");
    await settings.getByRole("switch", { name: "تفعيل المساعد المحلي", exact: true }).click();
    await settings.getByRole("switch", { name: "حفظ محادثة المساعد", exact: true }).click();
    await settings.getByRole("button", { name: "حفظ إعدادات المساعد المحلي", exact: true }).click();
    await expect(page.getByText("تم حفظ إعدادات المساعد المحلي", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(settings).not.toBeVisible();
    const ask = async (text: string) => {
      await panel.getByLabel("سؤال مساعد فينورا").fill(text);
      await panel.getByRole("button", { name: "إرسال سؤال المساعد", exact: true }).click();
      await expect(panel.getByRole("button", { name: "إيقاف إجابة المساعد", exact: true })).not.toBeVisible();
    };
    await panel.getByRole("button", { name: "المحادثة", exact: true }).click();
    await ask("اعرض رصيد العميل");
    await expect(
      panel.getByText("تمت القراءة من أدوات فينورا، راجع المصدر والمقترح أدناه.", { exact: true }),
    ).toBeVisible();
    await expect(panel.locator("details summary").filter({ hasText: "رصيد العميل" })).toBeVisible();
    expect(
      calls.some(
        (c) =>
          c.url === "/api/chat" &&
          (c.payload.messages as Array<{ role: string; tool_name?: string }>).some(
            (m) => m.role === "tool" && m.tool_name === "get_customer_balance",
          ),
      ),
    ).toBe(true);
    const saved = await page.evaluate(() => {
      const bridge = (window as Window & { finoraDesktop?: FinoraDesktopBridge }).finoraDesktop?.assistant;
      if (!bridge) throw Error("Missing assistant bridge");
      return bridge.historyLoad();
    });
    expect(saved.rows.length).toBe(2);
    await panel.getByRole("button", { name: "بحث البيانات", exact: true }).click();
    await panel.getByLabel("البحث ببيانات فينورا").fill("عميل");
    await panel.getByRole("button", { name: "بحث", exact: true }).click();
    await expect(panel.getByText("عميل اختبار", { exact: true })).toBeVisible();
    await panel.getByLabel("إعدادات المساعد المحلي").click();
    await settings.getByLabel("خدمة الذكاء المحلي").selectOption("lmstudio");
    await settings.getByLabel("منفذ الذكاء المحلي").fill(String(port));
    await settings.getByRole("button", { name: "فحص الاتصال وجلب النماذج" }).click();
    await settings.getByRole("button", { name: "حفظ إعدادات المساعد المحلي", exact: true }).click();
    await page.keyboard.press("Escape");
    await panel.getByRole("button", { name: "المحادثة", exact: true }).click();
    await ask("اشرح شرح طويل");
    await expect(panel.getByText(/شرح محلي طويل/)).toBeVisible();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setMinimumSize(360, 400));
    const sizes: Array<[number, number]> = [
      [1920, 1080],
      [1366, 768],
      [1024, 600],
      [768, 560],
      [480, 700],
    ];
    for (const [width, height] of sizes) {
      await app.evaluate(
        ({ BrowserWindow }, size) =>
          BrowserWindow.getAllWindows()[0]?.setContentSize(size[0] ?? 1366, size[1] ?? 768),
        [width, height],
      );
      // Windows DPI scaling in Electron 22 can round the client width by one CSS pixel.
      await expect
        .poll(async () => Math.abs((await page.evaluate(() => innerWidth)) - width))
        .toBeLessThanOrEqual(1);
      const fits = await panel.evaluate((node) => {
        const r = node.getBoundingClientRect(),
          send = node.querySelector('[aria-label="إرسال سؤال المساعد"]')?.getBoundingClientRect();
        if (!send) return false;
        return (
          r.left >= 0 &&
          r.right <= innerWidth + 1 &&
          r.top >= 0 &&
          r.bottom <= innerHeight + 1 &&
          send.bottom <= innerHeight + 1 &&
          node.scrollWidth <= node.clientWidth + 1
        );
      });
      expect(fits).toBe(true);
    }
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.setContentSize(1366, 768));
    await expect
      .poll(async () => Math.abs((await page.evaluate(() => innerWidth)) - 1366))
      .toBeLessThanOrEqual(1);
    await page.screenshot({ path: path.join(artifacts, "assistant-panel.png") });
    await ask("جهز منتج جديد");
    await expect(panel.getByText("منتج مقترح للمراجعة", { exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "مراجعة في النموذج الأصلي", exact: true }).click();
    await expect(page.getByLabel("اسم المنتج", { exact: true })).toHaveValue("منتج من المساعد");
    await page.getByLabel("فتح مساعد فينورا", { exact: true }).click();
    await ask("جهز منتج جديد");
    await panel.getByRole("button", { name: "مراجعة في النموذج الأصلي", exact: true }).last().click();
    await expect(panel.getByText(/أكمل النموذج المفتوح/)).toBeVisible();
    await panel.getByLabel("سؤال مساعد فينورا").focus();
    await page.keyboard.press("Control+s");
    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
    await expect(page.getByLabel("اسم المنتج", { exact: true })).toHaveValue("منتج من المساعد");
    expect(stub.requests.some((s) => /POST .*\/desktop\/chat/.test(s))).toBe(false);
    expect(stub.bodies.some((r) => /commands|checkout|payment$/.test(r.path))).toBe(false);
    expect(
      stub.requests.filter(
        (r) =>
          r.startsWith("POST ") &&
          !["POST /api/v1/desktop/auth/login", "POST /finora-ai/api/desktop/tool"].includes(r),
      ),
    ).toEqual([]);
    expect([...new Set(calls.map((c) => c.url))].sort()).toEqual(["/api/chat", "/v1/chat/completions"]);
    expect(errors).toEqual([]);
    await page.screenshot({ path: path.join(artifacts, "assistant-draft-review.png") });
    writeFileSync(
      path.join(artifacts, "acceptance.json"),
      JSON.stringify(
        {
          runtime: await app.evaluate(() => ({ electron: process.versions.electron, arch: process.arch })),
          errors,
          localRequests: calls.length,
          protocols: [...new Set(calls.map((c) => c.url))],
          tested_sizes: sizes,
          financialWrites: 0,
          asar_sha256: process.env.FINORA_E2E_EXECUTABLE
            ? createHash("sha256")
                .update(
                  readFileSync(
                    path.join(path.dirname(process.env.FINORA_E2E_EXECUTABLE), "resources/app.asar"),
                  ),
                )
                .digest("hex")
            : null,
        },
        null,
        2,
      ),
    );
  } catch (e) {
    failed = true;
    throw e;
  } finally {
    await closeIsolatedApp(app);
    await stub.close();
    await new Promise<void>((resolve) => model.close(() => resolve()));
    if (
      !failed &&
      path.dirname(directory) === os.tmpdir() &&
      path.basename(directory).startsWith("finora-local-ai-")
    )
      rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
});
