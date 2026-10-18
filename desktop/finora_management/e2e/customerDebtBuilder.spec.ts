import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import { startFinoraStub, STUB_CREDENTIALS } from "./finoraStub";

test("documented opening debt previews, saves once and appears in the customer receivables", async () => {
  test.setTimeout(120000);
  const stub = await startFinoraStub({ customers: true, finance: true, customerDebtBuilder: true });
  const profile = mkdtempSync(path.join(tmpdir(), "finora-debt-builder-e2e-"));
  if (
    path.dirname(profile) !== path.resolve(tmpdir()) ||
    !path.basename(profile).startsWith("finora-debt-builder-e2e-")
  )
    throw Error("Unsafe cleanup");
  const artifacts = path.resolve(__dirname, "../../../tests/_artifacts/erp-customers");
  mkdirSync(artifacts, { recursive: true });
  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    cwd: path.resolve(__dirname, ".."),
    env: { ...process.env, FINORA_SERVER_URL: stub.url, FINORA_USER_DATA_DIR: profile },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.getByLabel("معرف الشركة").fill(STUB_CREDENTIALS.tenantSlug);
    await page.getByLabel("اسم المستخدم").fill(STUB_CREDENTIALS.username);
    await page.getByLabel("كلمة المرور").fill(STUB_CREDENTIALS.password);
    await page.getByRole("button", { name: "تسجيل الدخول", exact: true }).click();
    await page.getByRole("button", { name: "العملاء", exact: true }).click();
    const customers = page.getByRole("dialog", { name: "العملاء", exact: true });
    await customers.getByRole("row").filter({ hasText: "أحمد العميل" }).click();
    const details = customers.getByRole("complementary", { name: "أحمد العميل", exact: true });
    await details.getByRole("button", { name: "تسجيل دين افتتاحي", exact: true }).click();
    const create = page.getByRole("dialog", { name: "تسجيل دين افتتاحي", exact: true });
    const save = create.getByRole("button", { name: "تسجيل الدين وترحيله", exact: true });
    await expect(save).toBeDisabled();
    const amount = create.getByLabel("مبلغ الدين الافتتاحي");
    await amount.click();
    await expect(amount).toHaveValue("");
    await amount.press("Control+a");
    await amount.pressSequentially("400000");
    await create.getByLabel("وصف الدين الافتتاحي").fill("رصيد متبقٍ حسب كشف خارجي");
    await expect(save).toBeDisabled();
    await create.getByLabel("مرجع مصدر الدين").fill("EXT-2026-001");
    await create.getByLabel("أول استحقاق جديد").fill("2027-01-31");
    await expect(create.getByRole("cell", { name: "2027-02-28", exact: true })).toBeVisible();
    await expect(create.getByRole("cell", { name: "2027-03-31", exact: true })).toBeVisible();
    await create.getByRole("button", { name: "شرح تقسيم الأقساط" }).click();
    await expect(page.getByRole("note")).toContainText("خارج فواتير FINORA");
    await page.keyboard.press("Escape");
    await expect(create).toBeVisible();
    for (const [width, height] of [
      [1536, 900],
      [1180, 700],
      [1024, 768],
    ] as const) {
      await app.evaluate(
        ({ BrowserWindow }, dimensions) => {
          const window = BrowserWindow.getAllWindows()[0];
          window?.setMinimumSize(900, 650);
          window?.setContentSize(dimensions.width, dimensions.height);
        },
        { width, height },
      );
      await expect
        .poll(async () => {
          const box = await create.boundingBox(),
            view = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
          return (
            !!box &&
            box.x >= 0 &&
            box.y >= 0 &&
            box.x + box.width <= view.width + 1 &&
            box.y + box.height <= view.height + 1
          );
        })
        .toBe(true);
      await expect(save).toBeInViewport();
      await expect
        .poll(
          async () =>
            (await create.getByRole("region", { name: "معاينة تقسيم الأقساط" }).boundingBox())?.height ?? 0,
        )
        .toBeGreaterThanOrEqual(200);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      await page.screenshot({ path: path.join(artifacts, `opening-debt-${width}.png`) });
    }
    expect(stub.bodies.filter((item) => item.path.endsWith("/debts"))).toHaveLength(0);
    await save.click();
    const schedule = page.getByRole("dialog", { name: "جدولة الأقساط #5", exact: true });
    await expect(schedule.getByLabel("قيمة القسط 1")).toHaveValue("133,333");
    await expect(schedule.getByLabel("قيمة القسط 3")).toHaveValue("133,334");
    await schedule.getByText("تاريخ تعديل الجدولة (1)", { exact: true }).click();
    await expect(
      schedule.getByText("EXT-2026-001 — رصيد متبقٍ حسب كشف خارجي", { exact: true }),
    ).toBeVisible();
    await schedule.getByRole("button", { name: "إغلاق الجدولة", exact: true }).click();
    await details.getByRole("tab", { name: "كشف المستحقات", exact: true }).click();
    await expect(details.getByText("دين افتتاحي · EXT-2026-001 · كشف خارجي", { exact: true })).toBeVisible();
    const writes = stub.bodies.filter((item) => item.path.endsWith("/debts"));
    expect(writes).toHaveLength(1);
    expect(writes[0]?.body).toMatchObject({
      source_type: "opening",
      source_reference: "EXT-2026-001",
      amount: 400000,
      count: 3,
      first_due_date: "2027-01-31",
      interval: "monthly",
    });
    expect(
      stub.bodies.filter((item) => item.path.startsWith("/api/finance") || item.path.startsWith("/orders")),
    ).toHaveLength(0);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    await stub.close();
    rmSync(profile, { recursive: true, force: true });
  }
});
