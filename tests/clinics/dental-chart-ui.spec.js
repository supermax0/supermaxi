import { test, expect } from "@playwright/test";
import path from "node:path";

const statuses = [
  ["healthy", "سليم"],
  ["caries", "تسوس"],
  ["filled", "حشوة"],
  ["temporary_filling", "حشوة مؤقتة"],
  ["root_canal", "علاج عصب"],
  ["crown", "تاج"],
  ["implant", "زرعة"],
  ["missing", "سن مفقود"],
  ["extraction_planned", "مقرر قلع"],
  ["fracture", "كسر"],
  ["other", "أخرى"],
].map(([code, label_ar]) => ({ code, label_ar }));

test("professional odontogram renders all teeth and saves from its detail drawer", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.setContent('<main style="padding:20px"><div id="chart"></div></main>');
  await page.addStyleTag({ path: path.resolve("static/clinics/dental-chart.css") });
  await page.addScriptTag({ path: path.resolve("static/clinics/dental-chart.js") });

  await page.evaluate(async ({ statuses }) => {
    const chart = {
      patient_id: 7,
      has_chart: true,
      dentition_mode: "permanent",
      permissions: { can_edit: true },
      teeth: [
        { tooth_number: "16", status: "caries", status_label_ar: "تسوس", surfaces: ["occlusal"], notes: "" },
        { tooth_number: "25", status: "root_canal", status_label_ar: "علاج عصب", surfaces: [], notes: "" },
        { tooth_number: "46", status: "filled", status_label_ar: "حشوة", surfaces: [], notes: "" },
      ],
      history_summary: { 24: { status_label_ar: "حشوة", visit_date: "2026-09-01", doctor_name: "د. أحمد" } },
      catalog: {
        statuses,
        surfaces: ["mesial", "distal", "occlusal", "buccal", "lingual", "incisal"],
      },
    };
    window.savedDentalPayload = null;
    const api = async (url, options = {}) => {
      if (url.endsWith("/procedures")) return [];
      if (url.includes("dental-treatment-plans")) return { items: [] };
      if (options.method === "PUT") {
        window.savedDentalPayload = JSON.parse(options.body);
        return chart;
      }
      return chart;
    };
    await window.ClinicsDentalChart.mount(document.getElementById("chart"), {
      visitId: 12,
      api,
      showNotice: () => {},
      readonly: false,
      patientId: 7,
    });
  }, { statuses });

  await expect(page.locator(".cx-dental__desktop [data-tooth]")).toHaveCount(32);
  await expect(page.locator(".cx-dental__desktop .cx-dental__identity small")).toHaveCount(32);
  await expect(page.locator('[data-tooth="11"] .cx-dental__identity')).toContainText("القاطع المركزي");
  await expect(page.locator('[data-tooth="18"] .cx-dental__identity')).toContainText("ضرس العقل");
  await expect(page.locator('[data-tooth="16"]')).toHaveClass(/is-caries/);
  await expect(page.locator('[data-tooth="25"]')).toHaveClass(/is-root-canal/);

  await page.locator('[data-tooth="16"]').click();
  await expect(page.locator(".cx-dental-drawer__panel")).toBeVisible();
  await page.locator('[data-status-choice="filled"]').click();
  await expect(page.locator("[data-tooth-preview]")).toHaveClass(/is-filled/);
  await page.locator('.cx-dental-drawer__surfaces input[value="buccal"]').check();
  await page.locator("[data-save]").click();

  await expect.poll(() => page.evaluate(() => window.savedDentalPayload?.status)).toBe("filled");
  await expect.poll(() => page.evaluate(() => window.savedDentalPayload?.surfaces?.sort())).toEqual(["buccal", "occlusal"]);
});
