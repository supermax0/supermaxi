import { readFileSync } from "node:fs";
import path from "node:path";
import { chromium, expect, test } from "@playwright/test";

for (const combined of [false, true])
  test(`store options: ${combined ? "size before color" : "size without color"}`, async () => {
    const root = path.resolve(__dirname, "../../..");
    const filename = combined
      ? "product-options-combination-preview.html"
      : "product-options-store-preview.html";
    const html = readFileSync(path.join(root, "tests/_artifacts", filename), "utf8");
    const browser = await chromium.launch({ channel: "chrome" });
    const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const writes: Record<string, unknown>[] = [],
      errors: string[] = [];
    let releaseCartResponse!: () => void;
    const cartResponse = new Promise<void>((resolve) => {
      releaseCartResponse = resolve;
    });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/shop/test/product/1")
        return route.fulfill({ contentType: "text/html", body: html });
      if (url.pathname === "/shop/test/api/cart/add") {
        writes.push(route.request().postDataJSON());
        await cartResponse;
        return route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ success: true, cart: { count: 1 } }),
        });
      }

      if (url.pathname.startsWith("/static/") && !url.pathname.includes("..")) {
        try {
          return await route.fulfill({ path: path.join(root, url.pathname) });
        } catch {
          /* optional media */
        }
      }
      return route.fulfill({ status: 404, body: "" });
    });
    try {
      await page.goto("https://store.test/shop/test/product/1");
      const add = page.getByRole("button", { name: "أضف إلى السلة", exact: true });
      await expect(add).toBeDisabled();
      const picker = page.locator("[data-sf-color-picker]");
      await picker.getByLabel("شرح خيارات المنتج").click();
      await expect(picker.getByText(/بالترتيب الذي يناسبك/)).toBeVisible();
      await picker.getByLabel("شرح خيارات المنتج").click();
      await expect(picker.locator("select")).toHaveCount(0);
      const size = page.getByRole("radiogroup", {
        name: combined ? "اختر المقاس" : "اختر الحجم",
        exact: true,
      });
      const color = page.getByRole("radiogroup", { name: "اختر اللون", exact: true });
      if (combined) {
        await color.getByRole("radio", { name: "أسود", exact: true }).click();
        await expect(add).toBeDisabled();
        await expect(page.locator(".lux-pd-price")).toContainText("180 – 250");
        await picker.getByRole("button", { name: "مسح اختيار اللون", exact: true }).click();
      }
      await size.getByRole("radio", { name: combined ? "M" : "100 مل", exact: true }).click();
      const main = page.locator("#sfMainImage");
      if (combined) {
        await expect(add).toBeDisabled();
        await expect(page.locator(".lux-pd-price")).toContainText("180 – 200");
        await color.getByRole("radio", { name: "أسود", exact: true }).click();
        await expect(color.getByRole("radio", { name: "أسود", exact: true })).toHaveAttribute(
          "aria-checked",
          "true",
        );
        await expect(
          color.getByRole("radio", { name: "أسود", exact: true }).locator(".sf-option-disc"),
        ).toHaveCSS("background-color", "rgb(37, 37, 43)");
        await expect(
          size.getByRole("radio", { name: "M", exact: true }).locator(".sf-option-disc"),
        ).toHaveCSS("border-radius", "50%");
      } else {
        await expect(color).toHaveCount(0);
        await expect(page.locator(".lux-pd-price")).toContainText("250");
      }
      const selected = picker.locator('[data-sf-color][aria-pressed="true"]');
      await expect(main).toHaveAttribute("src", (await selected.getAttribute("data-image")) ?? "");
      await expect(add).toBeEnabled();
      const selectedChoice = size.getByRole("radio", { name: combined ? "M" : "100 مل", exact: true });
      expect(
        await selectedChoice.evaluate((node) => {
          (node as HTMLButtonElement).click();
          const disc = node.querySelector(".sf-option-disc");
          if (!disc) throw Error("Missing option animation element");
          return disc.getAnimations().length;
        }),
      ).toBeGreaterThan(0);
      await add.click();
      await expect(add).toHaveAttribute("aria-busy", "true");
      await expect(add).toHaveClass(/is-loading/);
      await expect(add).toBeDisabled();
      releaseCartResponse();
      await expect(add).not.toHaveAttribute("aria-busy", "true");
      await expect(add).toBeEnabled();
      await expect.poll(() => writes.length).toBe(1);
      expect(writes[0]).toMatchObject({
        color: combined ? "المقاس: M / اللون: أسود" : "الحجم: 100 مل",
        quantity: 1,
      });
      if (combined) {
        await color.getByRole("radio", { name: "أبيض", exact: true }).click();
        await expect(add).toBeDisabled();
        await expect(picker.locator("[data-sf-option-status]")).toHaveText("غير متوفر حالياً");
        await expect(size.getByRole("radio", { name: "L", exact: true })).toBeDisabled();
        await expect(color.getByRole("radio", { name: "أبيض", exact: true })).toHaveClass(/is-unavailable/);
        await expect(
          color.getByRole("radio", { name: "أبيض", exact: true }).locator(".sf-option-disc"),
        ).toHaveCSS("background-color", "rgb(255, 255, 255)");
        await color.getByRole("radio", { name: "أسود", exact: true }).click();
      }
      if (combined) {
        await picker.getByRole("button", { name: "مسح اختيار اللون", exact: true }).click();
        await size.getByRole("radio", { name: "M", exact: true }).focus();
        await page.keyboard.press("ArrowLeft");
        await expect(size.getByRole("radio", { name: "L", exact: true })).toHaveAttribute(
          "aria-checked",
          "true",
        );
        await expect(color.getByRole("radio", { name: "أسود", exact: true })).toHaveAttribute(
          "aria-checked",
          "true",
        );
        await expect(add).toBeEnabled();
        await expect(page.locator(".lux-pd-price")).toContainText("250");
      }
      for (const width of [1365, 768, 390]) {
        await page.setViewportSize({ width, height: 900 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
        if (width === 390 && combined) {
          await size.getByRole("radio", { name: "M", exact: true }).click();
          await color.getByRole("radio", { name: "أبيض", exact: true }).click();
          await expect(add).toBeDisabled();
          await color.getByRole("radio", { name: "أسود", exact: true }).click();
          await expect(add).toBeEnabled();
        }
        await page.evaluate(() => window.scrollTo(0, 0));
        await expect(page.locator(".lux-pd-title")).toBeVisible();
        const layout = await page.locator("#luxProductDetail").evaluate((node) => {
          const galleryNode = node.querySelector(".lux-pd-gallery-wrap");
          const infoNode = node.querySelector(".lux-pd-info");
          if (!galleryNode || !infoNode) throw Error("Missing product layout");
          const gallery = galleryNode.getBoundingClientRect();
          const info = infoNode.getBoundingClientRect();
          return { galleryTop: gallery.top, galleryBottom: gallery.bottom, infoTop: info.top };
        });
        if (width > 900) expect(Math.abs(layout.galleryTop - layout.infoTop)).toBeLessThan(4);
        else expect(layout.infoTop).toBeGreaterThanOrEqual(layout.galleryBottom);
        await page.screenshot({
          path: path.join(
            root,
            "tests/_artifacts",
            `product-options-${combined ? "combined" : "size"}-${width}.png`,
          ),
          fullPage: true,
        });
      }
      if (combined) {
        await color.evaluate((node) => {
          const black = node.querySelector<HTMLButtonElement>('[data-sf-option-value="أسود"]');
          const white = node.querySelector<HTMLButtonElement>('[data-sf-option-value="أبيض"]');
          if (!black || !white) throw Error("Missing test color swatches");
          white.click();
          black.click();
          white.click();
          black.click();
        });
        await expect.poll(() => main.evaluate((node) => node.getAnimations().length)).toBe(0);
        await expect(main).toHaveAttribute("src", (await selected.getAttribute("data-image")) ?? "");
        await expect(page.locator(".lux-pd-price")).toContainText("180");
      }
      await page.emulateMedia({ reducedMotion: "reduce" });
      const reducedChoice = size.getByRole("radio", { name: combined ? "M" : "100 مل", exact: true });
      expect(
        await reducedChoice.evaluate((node) => {
          (node as HTMLButtonElement).click();
          const disc = node.querySelector(".sf-option-disc");
          if (!disc) throw Error("Missing option animation element");
          return disc.getAnimations().length;
        }),
      ).toBe(0);
      expect(
        await page
          .locator("#luxProductDetail")
          .evaluate((node) => node.getAnimations({ subtree: true }).length),
      ).toBe(0);
      if (combined) {
        await color.getByRole("radio", { name: "أبيض", exact: true }).click();
        await expect(add).toBeDisabled();
        await color.getByRole("radio", { name: "أسود", exact: true }).click();
      } else await size.getByRole("radio", { name: "50 مل", exact: true }).click();
      await expect(add).toBeEnabled();
      await expect(page.locator(".lux-pd-price")).toContainText("180");
      expect(errors).toEqual([]);
    } finally {
      await browser.close();
    }
  });

test("web inventory editor saves size options, photos and opening stock together", async () => {
  const root = path.resolve(__dirname, "../../..");
  const html = readFileSync(
    path.join(root, "tests/_artifacts/product-options-web-editor-preview.html"),
    "utf8",
  );
  const browser = await chromium.launch({ channel: "chrome" });
  const page = await browser.newPage();
  let saved = "";
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/inventory/preview") return route.fulfill({ contentType: "text/html", body: html });
    if (url.pathname === "/inventory/save") {
      saved = route.request().postDataBuffer()?.toString("utf8") ?? "";
      return route.fulfill({ contentType: "text/html", body: "تم الحفظ" });
    }
    if (url.pathname === "/static/js/product-options-editor.js")
      return route.fulfill({ path: path.join(root, url.pathname) });
    return route.fulfill({ status: 404, body: "" });
  });
  try {
    await page.goto("https://inventory.test/inventory/preview");
    await page.getByRole("checkbox", { name: "هذا المنتج عنده خيارات" }).check();
    await page.getByRole("button", { name: "الحجم فقط" }).click();
    for (const size of ["50 مل", "100 مل"]) {
      await page.getByLabel("قيمة الحجم").fill(size);
      await page.getByRole("button", { name: "إضافة خيار" }).click();
    }
    await page.getByLabel("مخزون الحجم: 50 مل").fill("4");
    await page.getByLabel("مخزون الحجم: 100 مل").fill("2");
    await page.getByLabel("سعر البيع الحجم: 100 مل").fill("25000");
    await page.getByLabel("صورة الحجم: 50 مل").setInputFiles({
      name: "photo.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5mQAAAAASUVORK5CYII=",
        "base64",
      ),
    });
    await expect(page.getByRole("img", { name: "الحجم: 50 مل", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "حفظ المنتج" }).click();
    await expect.poll(() => saved).toContain('name="product_options"');
    expect(saved).toContain('"axes":["الحجم"]');
    expect(saved).toContain('"qty":4');
    expect(saved).toContain('"sale_price":25000');
    expect(saved).toContain('name="color_image_0"; filename="photo.png"');
  } finally {
    await browser.close();
  }
});
