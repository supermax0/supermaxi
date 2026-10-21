import { mkdtempSync, rmSync } from "node:fs";
import { createServer, request } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test, type Locator } from "@playwright/test";
import { closeIsolatedApp } from "./closeIsolatedApp";
import { createFinanceFixture } from "./financeFixture";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("finance tables scroll to their last row while pagination stays outside the rows", async () => {
  test.setTimeout(180000);
  const stub = await startFinoraStub({ finance: true });
  const fixture = createFinanceFixture();
  const sources = Array.from({ length: 21 }, (_, index) => ({
    key: `source-${index}`,
    name: `مصدر مالي ${index + 1}`,
    type: "asset",
    target: 1000,
    current: 900,
    difference: 100,
    account_ids: [],
  }));
  const server = createServer((req, res) => {
    const url = new URL(req.url ?? "/", stub.url);
    let data: unknown;
    if (url.pathname === "/api/finance/meta") {
      const meta = fixture.handle(url.pathname, "GET", url, {});
      if (!meta) throw Error("Missing finance metadata fixture");
      data = { ...(meta.data as { data: Record<string, unknown> }).data, financial_control_available: true };
    } else if (url.pathname === "/api/finance/control/current") {
      data = {
        rows: sources,
        registered: { assets: 21000, liabilities: 0, net_assets: 21000 },
        ledger: {
          assets: 18900,
          liabilities: 0,
          net_assets: 18900,
          profit: 0,
          equity: 18900,
          balanced: true,
        },
        coverage_issues: [{ key: "source-gap", message: "فرق يحتاج مراجعة", amount: 2100 }],
        independent_branches: false,
        generated_at: "2026-10-21T10:00:00",
        basis_version: 1,
      };
    } else if (url.pathname === "/api/finance/journal") {
      data = {
        total: 67,
        rows: Array.from({ length: 25 }, (_, index) => ({
          id: index + 1,
          number: `JC-${index + 1}`,
          date: "2026-10-21",
          debit: "المخزون",
          credit: "رأس المال",
          amount: 1000,
          description: "وصف قيد طويل يوضح العملية المالية والملاحظات المرتبطة بها. ".repeat(5),
        })),
      };
    } else if (url.pathname === "/api/finance/control/snapshots") {
      data = {
        total: 67,
        page: 1,
        page_size: 25,
        items: Array.from({ length: 25 }, (_, index) => ({
          id: index + 1,
          name: `معاينة ${index + 1}`,
          created_at: "2026-10-21T10:00:00",
          created_by: "مدير الشركة",
          reason: "عد فعلي",
          net_assets: 21000,
          ledger_profit: 0,
          coverage_issues_count: 1,
        })),
      };
    }
    if (data !== undefined) {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ success: true, data }));
      return;
    }
    const upstream = request(
      new URL(req.url ?? "/", stub.url),
      { method: req.method, headers: req.headers },
      (response) => {
        res.writeHead(response.statusCode ?? 502, response.headers);
        response.pipe(res);
      },
    );
    upstream.on("error", () => {
      res.writeHead(502);
      res.end();
    });
    req.pipe(upstream);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw Error("Missing finance test address");
  const profile = mkdtempSync(path.join(tmpdir(), "finora-finance-scroll-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-finance-scroll-")
  )
    throw Error("Unsafe finance test cleanup");
  const packaged = process.env.FINORA_E2E_EXECUTABLE;
  const app = await electron.launch({
    ...(packaged ? { executablePath: packaged, args: [] } : { args: [path.resolve(__dirname, "..")] }),
    cwd: path.resolve(__dirname, ".."),
    env: {
      ...process.env,
      FINORA_SERVER_URL: `http://127.0.0.1:${address.port}`,
      FINORA_USER_DATA_DIR: profile,
    },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "المزيد", exact: true }).click();
    await page.getByRole("dialog", { name: "المزيد" }).getByText("الحسابات", { exact: true }).click();
    const panel = page.getByRole("dialog", { name: "الحسابات", exact: true });
    const checkScroll = async (region: Locator, rowCount: number) => {
      await expect(region.locator("tbody tr")).toHaveCount(rowCount);
      await region.scrollIntoViewIfNeeded();
      const frame = await panel.boundingBox();
      const bounds = await region.boundingBox();
      if (!frame || !bounds) throw Error("Finance table must have visible bounds");
      expect(bounds.height).toBeGreaterThan(40);
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(frame.y + frame.height - 10);
      const dimensions = await region.evaluate((element) => ({
        client: element.clientHeight,
        scroll: element.scrollHeight,
      }));
      expect(dimensions.scroll).toBeGreaterThan(dimensions.client + 20);
      await region.hover();
      await page.mouse.wheel(0, 10000);
      await expect.poll(() => region.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
      await region.evaluate((element) => {
        element.scrollTop = element.scrollHeight;
      });
      await expect(region.locator("tbody tr").last()).toBeInViewport();
      const last = await region.locator("tbody tr").last().boundingBox();
      if (!last) throw Error("Last finance row must be visible");
      expect(last.y + last.height).toBeLessThanOrEqual(bounds.y + bounds.height + 1);
    };
    for (const [width, height] of [
      [1920, 1080],
      [1366, 768],
      [1024, 768],
      [960, 600],
    ] as const) {
      await page.setViewportSize({ width: width, height: height });
      await expect
        .poll(async () => (await panel.boundingBox())?.width ?? Infinity)
        .toBeLessThanOrEqual(width);
      await panel.getByRole("tab", { name: "الرقابة المالية", exact: true }).click();
      await panel.getByRole("button", { name: "المصادر الحالية", exact: true }).click();
      await checkScroll(panel.getByRole("region", { name: "مصادر المركز المالي", exact: true }), 21);
      await panel.getByRole("button", { name: "المعاينات والمطابقة", exact: true }).click();
      await checkScroll(panel.getByRole("region", { name: "سجل معاينات المركز المالي", exact: true }), 25);
      await panel.getByLabel("عدد الصفوف").scrollIntoViewIfNeeded();
      await expect(panel.getByLabel("عدد الصفوف")).toBeInViewport();
      await panel.getByLabel("عدد الصفوف").click();
      await page.keyboard.press("Escape");
      await panel.getByRole("tab", { name: "القيود والتقارير", exact: true }).click();
      await checkScroll(panel.getByRole("region", { name: "القيود المحاسبية", exact: true }), 25);
      await panel.getByLabel("عدد الصفوف").scrollIntoViewIfNeeded();
      await expect(panel.getByLabel("عدد الصفوف")).toBeInViewport();
      await panel.getByLabel("عدد الصفوف").click();
      await page.keyboard.press("Escape");
      await page.screenshot({ path: `test-results/finance-scroll-${width}x${height}.png` });
    }
    expect(errors).toEqual([]);
  } finally {
    await closeIsolatedApp(app);
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
