import { readFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium, expect, test } from "@playwright/test";

type PrintState = { __printCalls: number };
// Generate isolated route HTML first with tests/test_cashier_admin_invoice_print.py.
for (const actor of ["cashier", "admin"])
  for (const mode of ["single", "batch"])
    test(`invoice printing: ${actor} ${mode}`, async () => {
      const root = path.resolve(__dirname, "../../..");
      const stem = `invoice-print-${actor}-${mode}`;
      const html = readFileSync(path.join(root, "tests/_artifacts", `${stem}.html`), "utf8");
      const expected = JSON.parse(
        readFileSync(path.join(root, "tests/_artifacts", `invoice-print-${actor}-expected.json`), "utf8"),
      ) as { ids: number[]; product: string; option: string; totals: number[] };
      const browser = await chromium.launch({ channel: "chrome" });
      const page = await browser.newPage({ viewport: { width: 1000, height: 1000 } });
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.addInitScript(() => {
        (window as unknown as PrintState).__printCalls = 0;
        window.print = () => {
          (window as unknown as PrintState).__printCalls++;
        };
      });
      await page.route("**/*", async (route) => {
        const url = new URL(route.request().url());
        if (url.hostname === "invoice.test" && url.pathname === "/invoice")
          return route.fulfill({ contentType: "text/html", body: html });
        if (url.hostname === "invoice.test" && url.pathname.startsWith("/static/"))
          return route.fulfill({ path: path.join(root, url.pathname) });
        return route.fulfill({ status: 204, body: "" });
      });
      try {
        await page.goto("https://invoice.test/invoice");
        const invoices =
          mode === "batch" ? page.locator(".invoice-frame-wrap") : page.locator(".invoice-container");
        await expect(invoices).toHaveCount(mode === "batch" ? 2 : 1);
        const qrUrls: string[] = [];
        for (let index = 0; index < (mode === "batch" ? 2 : 1); index++) {
          const invoice = invoices.nth(index);
          await expect(invoice.locator(".products-table tbody tr")).toHaveCount(1);
          await expect(invoice.locator(".product-name-col")).toContainText(expected.product);
          await expect(invoice.locator(".product-name-col")).toContainText(expected.option);
          const total = expected.totals[index];
          if (total === undefined) throw new Error(`Missing expected total for invoice ${index}`);
          await expect(invoice.locator(".total-box")).toContainText(total.toFixed(2));
          const barcode = invoice.locator("img[data-invoice-barcode]");
          await expect(barcode).toHaveAttribute("src", /^data:image\/svg\+xml;base64,/);
          const decodedNumber = await barcode.evaluate((element) => {
            const image = element as HTMLImageElement;
            const svg = new DOMParser().parseFromString(atob(image.src.split(",")[1] ?? ""), "image/svg+xml");
            return Array.from(svg.querySelectorAll("text"))
              .map((text) => text.textContent)
              .join("");
          });
          expect(decodedNumber).toBe(String(expected.ids[index]));
          const qr = invoice.locator("[data-invoice-qrcode] img");
          await expect(qr).toHaveAttribute("src", /^data:image\/svg\+xml;base64,/);
          for (const image of [barcode, qr])
            await expect
              .poll(() =>
                image.evaluate((element) => {
                  const printable = element as HTMLImageElement;
                  return printable.complete && printable.naturalWidth > 0;
                }),
              )
              .toBe(true);
          const qrUrl = await invoice.locator("[data-invoice-qrcode]").getAttribute("title");
          expect(qrUrl).toMatch(/^https?:\/\//);
          if (!qrUrl) throw new Error(`Missing QR link for invoice ${index}`);
          qrUrls.push(qrUrl);
        }
        expect(new Set(qrUrls).size).toBe(qrUrls.length);
        if (mode === "batch")
          await expect
            .poll(() => page.evaluate(() => (window as unknown as PrintState).__printCalls))
            .toBe(1);
        const printButton =
          mode === "batch"
            ? page.locator("#btn-print")
            : page.locator(".invoice-actions").getByRole("button", { name: "طباعة", exact: true });
        await expect(printButton).toBeVisible();
        await printButton.click({ timeout: 5000 });
        expect(await page.evaluate(() => (window as unknown as PrintState).__printCalls)).toBe(
          mode === "batch" ? 2 : 1,
        );
        await page.emulateMedia({ media: "print" });
        await expect(page.locator(mode === "batch" ? ".toolbar" : ".invoice-actions")).toBeHidden();
        expect(errors).toEqual([]);
        const output = path.join(root, "output/pdf");
        mkdirSync(output, { recursive: true });
        const pdf = await page.pdf({
          path: path.join(output, `${stem}.pdf`),
          format: "A4",
          printBackground: true,
        });
        // Chromium writes page dictionaries uncompressed; catch overflow/blank pages in the actual PDF.
        expect(pdf.toString("latin1").match(/\/Type\s*\/Page\b/g)?.length).toBe(mode === "batch" ? 2 : 1);
      } finally {
        await browser.close();
      }
    });
