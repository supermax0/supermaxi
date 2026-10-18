import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

// Explicit synthetic loopback fixture; never exercise live customer/message APIs.
test.use({ baseURL: "http://127.0.0.1:5099", channel: "chrome", headless: true });
const artifactDir = path.resolve("tests/_artifacts/employee-training");
const module = (page, id) => page.locator(`[data-module="${id}"]`);
async function open(page) {
  await page.goto("/employee-desk/training");
  await expect(page.locator("#load-status")).toBeHidden();
}

test("real screenshots, click targets, quizzes and resume through all desk lessons", async ({ page }) => {
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await open(page);
  const steps = { login: 4, messages: 2, reply: 3, booking: 8 };
  const answers = { login: 1, messages: 0, reply: 2, booking: 1 };
  for (const [id, count] of Object.entries(steps)) {
    await module(page, id).click();
    for (let i = 0; i < count; i++) {
      await expect(page.locator("#step-next")).toBeDisabled();
      await expect(page.locator("#step-image")).toHaveJSProperty("naturalWidth", 390);
      await page.locator("#hotspot").click();
      await expect(page.locator("#step-feedback")).toContainText("الصحيح");
      await page.locator("#step-next").click();
    }
    await page.locator(`#quiz-answers [data-answer="${answers[id]}"]`).click();
    await expect(module(page, id)).toHaveClass(/done/);
  }
  await page.reload();
  await expect(module(page, "booking")).toHaveClass(/active/);
  await expect(page.locator("#course-percent")).toHaveText("57%");
  await expect(page.locator("#step-counter")).toHaveText("خطوة 8 / 8");
  expect(errors).toEqual([]);
});

test("catalog, Arabic price recall, reply scenarios and booking practice perform no writes", async ({ page }) => {
  const writes = [];
  page.on("request", (req) => { if (!["GET", "HEAD"].includes(req.method())) writes.push(req.url()); });
  await open(page); await module(page, "products").click();
  await page.locator(".product-choice").click();
  await expect(page.locator("#product-detail")).toContainText("25,000");
  await page.locator("#start-price-quiz").click();
  await page.locator("#price-answer").fill("١٠٠");
  await page.locator("#price-form button").click();
  await expect(module(page, "products")).not.toHaveClass(/done/);
  await page.locator("#price-answer").fill("٢٥٬٠٠٠");
  await page.locator("#price-form button").click();
  await expect(module(page, "products")).toHaveClass(/done/);
  await module(page, "style").click();
  for (const choice of [1, 2, 0]) {
    await page.locator(`#scenario-answers [data-answer="${choice}"]`).click();
    await page.locator("#scenario-next").click();
  }
  await expect(module(page, "style")).toHaveClass(/done/);
  await module(page, "practice").click();
  await page.locator("#practice-reply").fill("أهلاً وسهلاً، سعر المنتج الأساسي ٢٥٠٠٠ دينار. خل أتأكدلك من التوصيل حسب منطقتك.");
  await page.locator('[name="customer"]').fill("زبون تدريبي");
  await page.locator('[name="phone"]').fill("٠٧٧٠٠٠٠٠٠٠٠");
  await page.locator('[name="city"]').fill("بغداد");
  await page.locator('[name="address"]').fill("منطقة تدريبية قرب المدرسة");
  await page.locator("#practice-color").selectOption("أسود");
  await page.locator("#practice-confirm").check();
  await page.locator("#practice-submit").click();
  await expect(page.locator("#practice-feedback")).toContainText("ما تم تسجيل طلب");
  await expect(module(page, "practice")).toHaveClass(/done/);
  expect(writes).toEqual([]);
});

test("catalog handles empty results, forbidden responses, retry and unsafe product text", async ({ page }) => {
  await open(page); await module(page, "products").click();
  await page.locator("#product-search").fill("missing-product");
  await page.locator("#product-search-form button").click();
  await expect(page.locator("#product-status")).toContainText("ماكو منتجات");
  await page.route("**/api/employee-desk/training/products?*", (route) => route.fulfill({ status: 403, json: { ok: false } }));
  await page.locator("#product-search-form button").click();
  await expect(page.locator("#product-status")).toContainText("انتهت الجلسة");
  await page.unroute("**/api/employee-desk/training/products?*");
  await page.route("**/api/employee-desk/training/products?*", (route) => route.fulfill({ json: { ok: true, products: [{
    id: 1, name: '<img src=x onerror="window.pwned=1">', price: 1000,
    description: "<script>window.pwned=1</script>", image_url: "javascript:window.pwned=1",
    specs: [{ label: "الموديل", value: "<b>Model</b>" }],
    dual_region_pricing: true, governorate_sale_price: 1500, primary_province: "بغداد",
    colors: [{ name: "أسود", sale_price: 1200, governorate_sale_price: 1600 }],
  }] } }));
  await page.locator("#product-search-form button").click();
  await page.locator(".product-choice").click();
  expect(await page.evaluate(() => window.pwned)).toBeUndefined();
  await expect(page.locator("#product-detail")).toContainText("<script>");
  await expect(page.locator("#product-detail")).toContainText("الموديل: <b>Model</b>");
  await expect(page.locator("#product-detail")).toContainText("1,500");
  await expect(page.locator("#product-detail")).toContainText("1,200");
  await expect(page.locator("#product-detail")).toContainText("1,600");
  await expect(page.locator("#product-detail img")).toHaveCount(0);
});

test("phone and desktop fit viewport and screenshot zoom works with keyboard", async ({ page }) => {
  await fs.mkdir(artifactDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await open(page);
  await expect(page.locator("#step-image")).toHaveJSProperty("naturalWidth", 390);
  await page.screenshot({ path: path.join(artifactDir, "academy-desktop.png"), fullPage: true });
  await page.locator("#zoom-image").click();
  await expect(page.locator("#image-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#image-dialog")).toBeHidden();
  for (const width of [360, 390, 768, 1024]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(artifactDir, "academy-phone.png"), fullPage: true });
  await module(page, "products").click();
  await page.locator(".product-choice").click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(artifactDir, "academy-products-phone.png"), fullPage: true });
});

test("blocked local storage does not prevent completing a lesson", async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new Error("storage unavailable"); };
    Storage.prototype.setItem = () => { throw new Error("storage unavailable"); };
  });
  await open(page);
  await expect(page.locator("#storage-note")).toContainText("غير متاح");
  await page.locator("#hotspot").click();
  await expect(page.locator("#step-next")).toBeEnabled();
});
