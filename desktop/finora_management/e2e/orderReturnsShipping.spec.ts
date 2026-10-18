import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("order receipt and full return update real FIFO and refund the original split accounts once", async () => {
  test.setTimeout(240000);
  const root = path.resolve(__dirname, "../../.."),
    outputs = path.join(root, "tests/_artifacts/erp-order-returns-shipping");
  mkdirSync(outputs, { recursive: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-order-returns-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-order-returns-")
  )
    throw Error("Unsafe test cleanup");
  const installed = "C:/Users/msi/AppData/Local/Programs/Python/Python311/python.exe";
  const server = spawn(
    process.env.FINORA_TEST_PYTHON ?? (existsSync(installed) ? installed : "python"),
    [path.join(root, "tests/_artifacts/erp-regression/order_lifecycle_electron_server.py")],
    {
      cwd: root,
      windowsHide: true,
      env: { ...process.env, FINORA_ORDER_UI_TEST: "1", PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
    },
  );
  let text = "";
  const setup = await new Promise<{
    url: string;
    orderId: number;
    cashId: number;
    bankId: number;
    companyId: number;
  }>((resolve, reject) => {
    const timer = setTimeout(() => reject(Error("Order backend did not start")), 60000);
    server.stdout.on("data", (chunk) => {
      text += String(chunk);
      const match = /ORDER_TEST_READY (\{[^\r\n]+\})/.exec(text);
      if (match) {
        clearTimeout(timer);
        resolve(
          JSON.parse(match[1] ?? "{}") as {
            url: string;
            orderId: number;
            cashId: number;
            bankId: number;
            companyId: number;
          },
        );
      }
    });
    server.once("error", reject);
    server.once("exit", (code) => {
      clearTimeout(timer);
      reject(Error(`Order backend exited ${code}`));
    });
  });
  const stub = await startFinoraStub({ orderLifecycleServer: setup.url });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  const state = async () =>
    (await (await fetch(`${setup.url}/__state__`)).json()) as {
      status: string;
      paid: number;
      quantity: number;
      receipt: string | null;
      cash: number;
      bank: number;
      value: number;
    };
  try {
    const page = await app.firstWindow(),
      errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "الطلبات", exact: true }).first().click();
    await page.getByRole("button", { name: `إجراءات الطلب ${setup.orderId}` }).click();
    await page.getByRole("menuitem", { name: "عرض التفاصيل", exact: true }).click();
    const drawer = page.getByRole("complementary", { name: `الطلب #${setup.orderId}` });
    await drawer.getByRole("button", { name: "إضافة وصل شركة النقل", exact: true }).click();
    const receipt = page.getByRole("dialog", { name: `وصل شركة النقل — الطلب #${setup.orderId}` });
    await expect(receipt.getByRole("radio", { name: "وصل واحد للطلب" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await receipt.getByLabel("شركة النقل", { exact: true }).selectOption(String(setup.companyId));
    await receipt.getByLabel("رقم وصل شركة النقل 1", { exact: true }).fill("SHIP-001");
    for (const width of [1536, 1180, 1024]) {
      await app.evaluate(({ BrowserWindow }, size) => {
        const window = BrowserWindow.getAllWindows()[0];
        window?.setMinimumSize(0, 0);
        window?.setContentSize(size, 850);
      }, width);
      await expect(receipt.getByRole("button", { name: "حفظ رقم الوصل", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => innerWidth)).toBe(width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(outputs, `receipt-${width}.png`) });
    }
    await receipt.getByRole("button", { name: "حفظ رقم الوصل", exact: true }).click();
    await expect(receipt).not.toBeVisible();
    await expect(drawer.getByText("SHIP-001", { exact: true })).toBeVisible();
    expect(await state()).toMatchObject({ status: "جاري الشحن", quantity: 4, value: 1000 });
    await drawer.getByRole("button", { name: "تعديل وصل شركة النقل", exact: true }).click();
    await receipt.getByRole("radio", { name: "وصل لكل قطعة" }).click();
    await receipt.getByLabel("رقم وصل شركة النقل 1", { exact: true }).fill("SHIP-A");
    await receipt.getByLabel("رقم وصل شركة النقل 2", { exact: true }).fill("SHIP-B");
    await receipt.getByRole("button", { name: "حفظ رقم الوصل", exact: true }).click();
    await expect(receipt).not.toBeVisible();
    await drawer.getByRole("button", { name: "تعديل وصل شركة النقل", exact: true }).click();
    await expect(receipt.getByLabel("رقم وصل شركة النقل 2", { exact: true })).toHaveValue("SHIP-B");
    await receipt.getByRole("radio", { name: "وصل واحد للطلب" }).click();
    await expect(receipt.getByText(/سيستبدل أرقام القطع السابقة/)).toBeVisible();
    await receipt.getByLabel("رقم وصل شركة النقل 1", { exact: true }).fill("SHIP-C");
    await receipt.getByRole("button", { name: "حفظ رقم الوصل", exact: true }).click();
    await expect(receipt).not.toBeVisible();
    await drawer.getByRole("button", { name: /^تسديد/ }).click();
    const payment = page.getByRole("dialog", { name: `تسديد الطلب #${setup.orderId}` });
    await payment.getByRole("button", { name: "تقسيم الدفعة على أكثر من حساب" }).click();
    await payment.getByLabel("حساب الدفعة 1", { exact: true }).selectOption(String(setup.cashId));
    await payment.getByLabel("حساب الدفعة 2", { exact: true }).selectOption(String(setup.bankId));
    for (const number of [1, 2]) {
      const field = payment.getByLabel(`مبلغ الدفعة ${number}`, { exact: true });
      await field.click();
      await field.press("Control+a");
      await field.pressSequentially("400");
    }
    await payment.getByRole("button", { name: /تأكيد التسديد/ }).click();
    await expect(payment).not.toBeVisible();
    expect(await state()).toMatchObject({ paid: 800, cash: 20000400, bank: 400, quantity: 4 });
    // Exercise the real sandboxed invoice page without sending paper to a printer.
    await app.context().addInitScript(() => {
      window.print = () => {
        document.documentElement.dataset.testPrintRequested = "true";
      };
    });
    const printing = app.waitForEvent("window");
    await drawer.getByRole("button", { name: "طباعة", exact: true }).click();
    const printPage = await printing;
    await expect(printPage.getByText("SHIP-C", { exact: true })).toBeVisible({ timeout: 30000 });
    await printPage.screenshot({ path: path.join(outputs, "invoice-receipt-preview.png") });
    const printed = await app.evaluate(async ({ BrowserWindow }, origin) => {
      const window = BrowserWindow.getAllWindows().find((row) =>
        row.webContents.getURL().startsWith(origin + "/orders/print-invoices"),
      );
      if (!window) throw Error("Missing native invoice window");
      const bytes = await window.webContents.printToPDF({ printBackground: true, preferCSSPageSize: true });
      return { id: window.id, pdf: bytes.toString("base64") };
    }, stub.url);
    writeFileSync(path.join(outputs, "invoice-receipt.pdf"), Buffer.from(printed.pdf, "base64"));
    await app.evaluate(({ BrowserWindow }, id) => BrowserWindow.fromId(id)?.close(), printed.id);
    await drawer.getByRole("button", { name: "إرجاع الطلب", exact: true }).click();
    const branches = page.getByRole("dialog", { name: "إرجاع الطلبات", exact: true });
    await branches.getByRole("radio", { name: "Finance", exact: true }).click();
    await branches.getByRole("button", { name: "مراجعة الإرجاع", exact: true }).click();
    const confirmation = page.getByRole("dialog", { name: "تأكيد إرجاع الطلب", exact: true });
    await page.screenshot({ path: path.join(outputs, "return-confirmation.png") });
    expect(stub.bodies.filter((entry) => entry.path === "/orders/bulk-return")).toHaveLength(0);
    await confirmation.getByRole("button", { name: "تأكيد الإرجاع", exact: true }).click();
    await expect(confirmation).not.toBeVisible();
    const final = await state();
    expect(final).toMatchObject({
      status: "راجع",
      paid: 0,
      cash: 20000000,
      bank: 0,
      quantity: 6,
      value: 1200,
      receipt: null,
    });
    await expect(drawer.getByRole("button", { name: "إرجاع الطلب", exact: true })).not.toBeVisible();
    await drawer.getByRole("tab", { name: "سجل الحركات", exact: true }).click();
    await expect(drawer.getByText(/من SHIP-A \| SHIP-B إلى SHIP-C/)).toBeVisible();
    await page.screenshot({ path: path.join(outputs, "returned-history.png") });
    writeFileSync(path.join(outputs, "verified-state.json"), JSON.stringify(final, null, 2));
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    await stub.close();
    await fetch(`${setup.url}/__shutdown__`).catch(() => undefined);
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
    rmSync(profile, { recursive: true, force: true });
  }
});
