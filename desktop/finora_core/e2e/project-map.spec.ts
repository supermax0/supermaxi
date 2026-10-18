import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";

test("project map opens details, follows links, and exports complete specs", async ({ page }) => {
  const fixture = JSON.parse(
    await fs.readFile(new URL("./project-map-fixture.json", import.meta.url), "utf-8"),
  ) as { nodes: { position: { x: number; y: number } }[] };
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/e2e/project-map-preview.html");
  await page.getByRole("button", { name: "فتح مخطط الصفحات والميزات" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  const fullDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "تصدير", exact: true }).click();
  const fullPath = await (await fullDownload).path();
  if (!fullPath) throw new Error("Full map export missing");
  const fullGraph = JSON.parse(await fs.readFile(fullPath, "utf-8"));
  expect(fullGraph.nodes).toHaveLength(fixture.nodes.length);
  expect(fullGraph.nodes.map((n: { position: { x: number; y: number } }) => n.position)).toEqual(
    fixture.nodes.map((n) => n.position),
  );
  await page.locator(".react-flow__node").filter({ hasText: "الملاعب" }).click();
  await expect(page.getByRole("complementary", { name: "تفاصيل العنصر" })).toContainText(
    "البحث يعرض الملاعب المتاحة فقط",
  );
  await page.getByRole("button", { name: "الميزات وترابطها", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await page.locator(".react-flow__node").filter({ hasText: "صور" }).click();
  await expect(page.locator(".pm-details h3")).toHaveText("صور");
  await page.getByLabel("بحث بالمخطط").fill("صور");
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
  await page.getByRole("button", { name: "مسارات العمل", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await expect(page.locator(".react-flow__edge-text").filter({ hasText: "الموعد متاح" })).toHaveCount(1);
  const allFit = () =>
    page.evaluate(() => {
      const canvas = document.querySelector(".pm-canvas")?.getBoundingClientRect();
      if (!canvas) return false;
      return [...document.querySelectorAll(".react-flow__node")].every((n) => {
        const r = n.getBoundingClientRect();
        return (
          r.left >= canvas.left - 2 &&
          r.right <= canvas.right + 2 &&
          r.top >= canvas.top - 2 &&
          r.bottom <= canvas.bottom + 2
        );
      });
    });
  await expect.poll(allFit).toBe(true);
  await page.screenshot({ path: "test-results/project-map-workflow.png" });
  await page.getByRole("button", { name: "كل الترابطات", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(16);
  await expect.poll(allFit).toBe(true);
  await page.screenshot({ path: "test-results/project-map-all.png" });
  for (const format of ["json", "n8n", "svg"]) {
    await page.getByLabel("نوع التصدير").selectOption(format);
    const downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: "تصدير", exact: true }).click();
    const file = await downloading;
    const path = await file.path();
    if (!path) throw new Error("Export did not produce a file");
    const output = await fs.readFile(path, "utf-8");
    if (format === "svg") expect(output).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    else {
      const data = JSON.parse(output);
      expect(data.nodes).toHaveLength(16);
      if (format === "n8n") expect(data.nodes.every((n: { disabled: boolean }) => n.disabled)).toBe(true);
      else expect(data.edges.length).toBeGreaterThan(15);
    }
  }
  await page.getByRole("button", { name: "ربط MCP", exact: true }).click();
  await page.getByRole("button", { name: /إنشاء اتصال قراءة/ }).click();
  await expect(page.getByLabel("إعداد اتصال MCP")).toContainText("test-only-no-access");
  await page.getByRole("button", { name: "إغلاق إعداد الربط" }).click();
  await page.getByRole("button", { name: "ربط MCP", exact: true }).click();
  await expect(page.getByLabel("إعداد اتصال MCP")).toHaveCount(0);
  await page.getByRole("button", { name: "إغلاق إعداد الربط" }).click();
  await page.getByRole("button", { name: "إغلاق المخطط" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
});
