import { test, expect } from "@playwright/test";
import path from "node:path";

test("purchase review marks new products and converts USD at 1350", async ({ page }) => {
  await page.setContent('<main id="purchase-root"></main>');
  await page.addStyleTag({ path: path.resolve("static/workspace/css/workspace.css") });
  await page.addScriptTag({
    path: path.resolve("static/workspace/js/windows/purchase-invoice-analysis-window.js"),
  });

  await page.evaluate(() => {
    window.purchaseReviewCalls = [];
    window.PurchaseInvoiceAnalysisWindow.render(
      document.getElementById("purchase-root"),
      {
        props: {
          analysis: {
            supplier: { source_name: "المورد" },
            invoice: { currency: "IQD" },
            posting: { status: "not_posted" },
            summary: { new_product_rows: 1, total_units: 2, grand_total: 2, blocking: [] },
            rows: [{
              row_index: 1,
              decision: "create_new",
              status: "new_product",
              product_name: "منتج تجريبي",
              quantity: 2,
              unit_price: 1,
              line_total: 2,
              validation: [],
            }],
          },
        },
      },
      {
        onDecision: async (...args) => window.purchaseReviewCalls.push(["decision", ...args.slice(1)]),
        onValues: async (...args) => window.purchaseReviewCalls.push(["values", ...args.slice(1)]),
      }
    );
  });

  const newProduct = page.locator('[data-purchase-decision="create_new"]');
  await expect(newProduct).toHaveText("✓ منتج جديد");
  await expect(newProduct).toHaveAttribute("aria-pressed", "true");

  await page.locator('[data-purchase-price-usd="1"]').fill("12.50");
  await expect(page.locator('[data-purchase-price="1"]')).toHaveValue("16875");
  await expect(page.locator('[data-purchase-line-total="1"]')).toHaveText("33,750");
  await expect(page.locator('[data-metric-key="purchase-grand-total"] strong')).toHaveText("33,750");
  await expect(page.locator("[data-purchase-footer-total]")).toHaveText("33,750");
  await expect(page.locator("[data-purchase-unsaved]")).toBeVisible();
  await expect(page.locator(".ws-purchase-prepare")).toBeDisabled();
  await expect(page.locator(".ws-purchase-prepare")).toHaveText("احفظ تغييرات الأسعار أولاً");

  await page.locator('[data-purchase-values="1"]').click();
  await expect.poll(() => page.evaluate(() => window.purchaseReviewCalls.at(-1))).toEqual([
    "values", 1, 2, 16875, "منتج تجريبي", 12.5,
  ]);

  await newProduct.click();
  await expect.poll(() => page.evaluate(() => window.purchaseReviewCalls.at(-1)?.slice(0, 3))).toEqual([
    "decision", 1, "create_new",
  ]);
});
