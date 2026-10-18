import { mkdirSync } from "node:fs";
import path from "node:path";
import { test, expect, chromium, type Page } from "@playwright/test";
import { startAuditServer } from "./auditServer";

test("FIFO basis preview and explicit repair post only the physical count difference", async () => {
  test.setTimeout(180000);
  const server = await startAuditServer();
  const browser = await chromium.launch({ channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  try {
    await page.request.post(`${server.url}/api/v1/desktop/auth/login`, { data: {} });
    await page.request.post(`${server.url}/__audit_test/seed-cost-basis`);
    const base = `${server.url}/api/v1/desktop/inventory-audits`;
    const create = await page.request.post(base, {
      data: {
        idempotency_key: crypto.randomUUID(),
        ledger_kind: "branch",
        location_keys: ["branch:1"],
        title: "اختبار مطابقة التكلفة",
      },
    });
    const id = (await create.json()).data.session_id as number;
    const post = async (data: Record<string, unknown>) => {
      const r = await page.request.post(`${base}/${id}/commands`, {
        data: { ...data, idempotency_key: crypto.randomUUID() },
      });
      expect(r.ok()).toBe(true);
      return (await r.json()).data;
    };
    const rows = (await (await page.request.get(`${base}/${id}/lines`)).json()).data.items;
    const line = rows.find((r: { product: { sku: string } }) => r.product.sku === "TV55");
    const ticket = await post({ action: "begin_count", line_id: line.id, version: line.version });
    const count = await post({
      action: "save_count",
      line_id: line.id,
      version: ticket.version,
      ticket: ticket.ticket,
      quantity: 10,
    });
    await post({
      action: "review_line",
      line_id: line.id,
      version: count.version,
      resolution: "loss",
      reason: "عد فعلي مؤكد",
    });
    const get = async () => (await (await page.request.get(`${base}/${id}`)).json()).data;
    await post({ action: "submit", version: (await get()).version, acknowledge_partial: true });
    await post({ action: "approve", version: (await get()).version });
    await page.goto(`${server.url}/inventory/smart-audit?session=${id}`);
    await page.getByRole("button", { name: "مراجعة واعتماد الجرد", exact: true }).click();
    const review = page.getByRole("dialog", { name: "مراجعة نتائج الجرد", exact: true });
    await review.getByRole("button", { name: "فحص مطابقة طبقات التكلفة", exact: true }).click();
    const acknowledge = review.getByRole("checkbox", {
      name: "مطابقة طبقات التكلفة مع رصيد الفرع ضمن الترحيل، مع حفظ السبب أدناه",
    });
    await expect(acknowledge).toBeVisible();
    await acknowledge.check();
    await expect(review.getByRole("button", { name: "ترحيل التسويات المعتمدة", exact: true })).toBeDisabled();
    await review
      .getByPlaceholder("ملاحظة المراجعة / سبب إعادة فتح العد")
      .fill("إصلاح أساس FIFO قبل تسوية فرق الجرد الفعلي");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({
      path: path.resolve(
        __dirname,
        "../../../tests/_artifacts/smart-inventory-audit/live-completion/basis-mobile.png",
      ),
      animations: "disabled",
    });
    await review.getByRole("button", { name: "ترحيل التسويات المعتمدة", exact: true }).click();
    await expect(review).toContainText("مرحّل");
    const state = await (await page.request.get(`${server.url}/__audit_test/state`)).json();
    expect(state.stocks).toEqual([10, 4, 0]);
    expect(state.journals).toBe(1);
    expect(state.cash).toBe(0);
    expect(state.vouchers).toBe(0);
    const history = (await (await page.request.get(`${base}/${id}/history`)).json()).data.items;
    const event = history.find((r: { action: string }) => r.action === "post");
    expect(event.detail.changes[0].cost).toBe(200);
    expect(event.detail.valuation_reconciliation.removed_units).toBe(5);
  } finally {
    await browser.close();
    await server.close();
  }
});

test("real inventory audit: responsive counting, investigation, review, posting and saved reports", async () => {
  test.setTimeout(180000);
  const browser = await chromium.launch({ channel: "chrome" });
  const server = await startAuditServer();
  const artifacts = path.resolve(__dirname, "../../../tests/_artifacts/smart-inventory-audit");
  mkdirSync(artifacts, { recursive: true });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  page.setDefaultTimeout(15000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const state = async () => (await page.request.get(`${server.url}/__audit_test/state`)).json();
  const noOverflow = async (surface: Page) => {
    expect(await surface.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  };
  try {
    await page.request.post(`${server.url}/api/v1/desktop/auth/login`, { data: {} });
    await page.goto(`${server.url}/inventory/smart-audit`);
    await page.getByRole("button", { name: "جلسة جديدة", exact: true }).click();
    const create = page.getByRole("dialog", { name: "بدء جلسة جرد", exact: true });
    await create.getByLabel("عنوان جلسة الجرد").fill("الجرد المتكامل للفروع");
    await create.getByRole("button", { name: "كل المواقع المسموحة", exact: true }).click();
    await create.getByRole("button", { name: "بدء الجرد", exact: true }).click();
    await expect(page.getByLabel("موقع العد")).toBeVisible();
    const count = async (sku: string, quantity: string) => {
      await page.getByLabel("بحث أصناف الجرد").fill(sku);
      await page.getByLabel("نتائج بحث الجرد").getByRole("button").filter({ hasText: sku }).first().click();
      const input = page.getByLabel("العدد الفعلي", { exact: true });
      await expect(page.getByLabel("بحث أصناف الجرد")).toHaveValue("");
      await expect(page.getByLabel("نتائج بحث الجرد")).toHaveCount(0);
      await expect(input).toBeFocused();
      await expect(input).toBeInViewport();
      await input.fill(quantity);
      await page.getByRole("button", { name: "إضافة إلى الجرد", exact: true }).click();
      await expect(page.getByRole("button", { name: "إعادة العد", exact: true })).toBeVisible();
    };
    console.log("audit: counting first site");
    await count("TV55", "10");
    expect((await state()).stocks).toEqual([12, 4, 0]);
    await page.getByRole("button", { name: "رابط الموقع", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "رابط الجرد على الموقع", exact: true })).toHaveValue(
      /\/inventory\/smart-audit\?session=\d+$/,
    );
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "إيقاف مؤقت", exact: true }).click();
    await expect(page.getByRole("button", { name: "استئناف الجرد", exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("button", { name: "استئناف الجرد", exact: true })).toBeVisible();
    await expect(
      page
        .locator("article")
        .filter({ hasText: "شاشة 55" })
        .first()
        .getByText(/الفعلي/),
    ).toContainText("10");
    await page.getByRole("button", { name: "استئناف الجرد", exact: true }).click();
    await expect(page.getByRole("button", { name: "إيقاف مؤقت", exact: true })).toBeVisible();
    await page.getByLabel("بحث أصناف الجرد").fill("ZERO");
    await page.getByLabel("نتائج بحث الجرد").getByRole("button").filter({ hasText: "ZERO" }).first().click();
    await page.getByLabel("العدد الفعلي", { exact: true }).fill("2");
    await page.getByRole("button", { name: "إضافة إلى الجرد", exact: true }).click();
    await expect(page.getByRole("button", { name: "إعادة العد", exact: true })).toBeVisible();
    await page.getByLabel("بحث أصناف الجرد").fill("");
    await page.getByLabel("موقع العد").selectOption("branch:2");
    await count("TV55", "6");
    await page.getByLabel("بحث أصناف الجرد").fill("");
    await page.getByLabel("موقع العد").selectOption("branch:1");
    const editedRow = page.locator("article").filter({ hasText: "شاشة 55" }).first();
    await editedRow.getByRole("button", { name: "تعديل العدد / إعادة العد", exact: true }).click();
    await page.getByLabel("العدد الفعلي", { exact: true }).fill("9");
    await page.getByRole("button", { name: "إلغاء الإدخال", exact: true }).click();
    await expect(editedRow.getByText(/الفعلي/)).toContainText("10");
    for (const quantity of ["11", "10"]) {
      await editedRow.getByRole("button", { name: "تعديل العدد / إعادة العد", exact: true }).click();
      await page.getByLabel("العدد الفعلي", { exact: true }).fill(quantity);
      await page.getByRole("button", { name: "إضافة إلى الجرد", exact: true }).click();
      await expect(editedRow.getByText(/الفعلي/)).toContainText(quantity);
      await page.getByRole("button", { name: "إغلاق البطاقة", exact: true }).click();
    }
    expect((await state()).stocks).toEqual([12, 4, 0]);
    await expect(page.getByText("تمت إضافة المنتج للجرد", { exact: true })).toHaveCount(0);
    console.log("audit: responsive inspection");
    for (const [width, height] of [
      [390, 844],
      [768, 1024],
      [1536, 900],
      [844, 390],
    ] as const) {
      await page.setViewportSize({ width, height });
      await noOverflow(page);
      await page
        .getByRole("button", { name: "إنهاء الجرد ومراجعة النتائج", exact: true })
        .scrollIntoViewIfNeeded();
      await expect(
        page.getByRole("button", { name: "إنهاء الجرد ومراجعة النتائج", exact: true }),
      ).toBeInViewport();
      await page.screenshot({
        path: path.join(artifacts, `count-${width}x${height}.png`),
        fullPage: true,
        animations: "disabled",
        timeout: 10000,
      });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    const reviewLine = async (name: string) => {
      const row = page.locator("article").filter({ hasText: name }).first();
      await row.getByRole("button", { name: "التفاصيل", exact: true }).click();
      const detail = page.getByRole("dialog", { name: "تفاصيل المنتج بالجرد", exact: true });
      await detail.getByLabel("سبب فرق الجرد").fill("عد فعلي ومراجعة مستندات المصدر");
      await detail.getByRole("button", { name: "تثبيت سبب التسوية", exact: true }).click();
      await expect(detail.getByRole("button", { name: "تثبيت سبب التسوية", exact: true })).toBeEnabled();
      await detail.locator("h3").first().scrollIntoViewIfNeeded();
      await noOverflow(page);
      await page.screenshot({
        path: path.join(artifacts, `detail-${name.includes("صفري") ? "zero" : "tv"}.png`),
        fullPage: true,
        animations: "disabled",
        timeout: 10000,
      });
      await detail.getByLabel("إغلاق التفاصيل").click();
    };
    await reviewLine("شاشة 55");
    await reviewLine("صنف صفري");
    await page.getByLabel("موقع العد").selectOption("branch:2");
    await reviewLine("شاشة 55");
    await page.getByRole("button", { name: "إنهاء الجرد ومراجعة النتائج", exact: true }).click();
    const review = page.getByRole("dialog", { name: /مراجعة/ });
    await review.getByRole("button", { name: "إرسال الجرد للمراجعة", exact: true }).click();
    await review.getByRole("button", { name: "اعتماد الجرد", exact: true }).click();
    expect((await state()).stocks).toEqual([12, 4, 0]);
    await review.getByRole("button", { name: "ترحيل التسويات المعتمدة", exact: true }).click();
    await expect(review).toContainText("مرحّل");
    const result = await state();
    expect(result.stocks).toEqual([10, 6, 2]);
    expect(result.journals).toBe(3);
    expect(result.cash).toBe(0);
    expect(result.vouchers).toBe(0);
    const sessionId = result.sessions[0].id as number;
    const report = await page.request.get(`${server.url}/api/v1/desktop/inventory-audits/${sessionId}/print`);
    expect(report.ok()).toBe(true);
    const reportPage = await browser.newPage();
    await reportPage.goto(`${server.url}/api/v1/desktop/inventory-audits/${sessionId}/print`);
    await expect(reportPage.getByText("الجرد المتكامل للفروع")).toBeVisible();
    await reportPage.pdf({
      path: path.join(artifacts, "audit-report.pdf"),
      printBackground: true,
      preferCSSPageSize: true,
    });
    const excel = await page.request.get(`${server.url}/api/v1/desktop/inventory-audits/${sessionId}/xlsx`);
    expect(excel.ok()).toBe(true);
    expect((await excel.body()).subarray(0, 2).toString()).toBe("PK");
    await page.reload();
    await expect(page.getByText("مرحّل", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "عرض تقرير الجرد", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "سجل الجرد", exact: true }).click();
    await page.getByRole("button", { name: /الجرد المتكامل للفروع/ }).click();
    await expect(page.getByRole("button", { name: "عرض تقرير الجرد", exact: true })).toBeVisible();
    expect((await state()).journals).toBe(3);
    expect(errors).toEqual([]);
  } catch (error) {
    console.log(server.log());
    console.log((await page.locator("body").innerText({ timeout: 3000 })).slice(-5000));
    throw error;
  } finally {
    await browser.close();
    await server.close();
  }
});
