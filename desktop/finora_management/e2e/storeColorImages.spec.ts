import { readFileSync } from "node:fs";
import path from "node:path";
import { chromium, expect, test } from "@playwright/test";

test("store color selection swaps photos, preserves selection, and reaches the cart", async () => {
  const root = path.resolve(__dirname, "../../..");
  const html = readFileSync(path.join(root, "tests/_artifacts/color-photo-store-preview.html"), "utf8");
  const browser = await chromium.launch({ channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
  const writes: Record<string, unknown>[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/shop/test/product/1")
      return route.fulfill({ contentType: "text/html", body: html });
    if (url.pathname === "/shop/test/api/cart/add") {
      writes.push(route.request().postDataJSON());
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: true, cart: { count: 1 } }),
      });
    }
    if (url.pathname.startsWith("/static/") && !url.pathname.includes("..")) {
      try {
        return route.fulfill({ path: path.join(root, url.pathname) });
      } catch {
        /* optional asset */
      }
    }
    return route.fulfill({ status: 404, body: "" });
  });
  try {
    await page.goto("https://store.test/shop/test/product/1");
    const picker = page.locator("[data-sf-color-picker]");
    const white = picker.getByRole("button", { name: "أبيض", exact: true });
    const black = picker.getByRole("button", { name: "أسود", exact: true });
    const main = page.locator("#sfMainImage");
    await expect(white).toHaveAttribute("aria-pressed", "true");
    await expect(white.locator(".sf-option-disc")).toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(black.locator(".sf-option-disc")).toHaveCSS("background-color", "rgb(37, 37, 43)");
    await black.click();
    await expect(main).toHaveAttribute("src", (await black.getAttribute("data-image")) ?? "");
    await page.waitForTimeout(5300);
    await expect(main).toHaveAttribute("src", (await black.getAttribute("data-image")) ?? "");
    await page.screenshot({
      path: path.join(root, "tests/_artifacts/store-color-photos-desktop.png"),
      fullPage: true,
    });
    await page.locator("#sfQuantity").fill("3");
    await page.getByRole("button", { name: "أضف إلى السلة", exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0]).toMatchObject({ color: "أسود", quantity: 3, sale_mode: "normal" });
    await picker.getByRole("button", { name: /فضي/ }).click();
    await expect(main).toHaveAttribute("src", (await picker.getAttribute("data-base-image")) ?? "");
    await expect(page.getByRole("button", { name: "أضف إلى السلة", exact: true })).toBeDisabled();
    await page.setViewportSize({ width: 390, height: 844 });
    await white.click();
    await expect(main).toHaveAttribute("src", (await white.getAttribute("data-image")) ?? "");
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await page.screenshot({
      path: path.join(root, "tests/_artifacts/store-color-photos-mobile.png"),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await browser.close();
  }
});
