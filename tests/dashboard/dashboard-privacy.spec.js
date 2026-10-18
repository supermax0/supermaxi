import { existsSync, readFileSync } from "node:fs";
import { chromium, test, expect } from "@playwright/test";

const dashboardTemplate = readFileSync(
  new URL("../../templates/dashbord.html", import.meta.url),
  "utf8"
);
const baseTemplate = readFileSync(
  new URL("../../templates/base.html", import.meta.url),
  "utf8"
);

const privacyScript = dashboardTemplate.match(
  /const DASHBOARD_PRIVACY_MASK[\s\S]*?(?=\n  function fetchJson)/
)?.[0];
const topbarActionsBlock = dashboardTemplate.match(
  /{% block topbar_actions %}([\s\S]*?){% endblock %}/
)?.[1];
const userBoxActionsBlock = dashboardTemplate.match(
  /{% block user_box_actions %}([\s\S]*?){% endblock %}/
)?.[1];
const baseTopbarActionsBlock = baseTemplate.match(
  /{% block topbar_actions %}([\s\S]*?){% endblock %}/
)?.[1];
const baseUserBoxActionsBlock = baseTemplate.match(
  /{% block user_box_actions %}([\s\S]*?){% endblock %}/
)?.[1];

test("dashboard values stay masked and are revealed for only 30 seconds", async () => {
  expect(privacyScript).toBeTruthy();
  expect(dashboardTemplate).toContain(
    'privacyBtn.addEventListener("click", toggleDashboardPrivateValues)'
  );
  expect(dashboardTemplate).toContain('card.addEventListener("mouseenter"');
  expect(topbarActionsBlock).not.toContain('href="/pos"');
  expect(userBoxActionsBlock).toContain('href="/pos"');
  expect(baseTopbarActionsBlock).not.toContain('href="/pos"');
  expect(baseUserBoxActionsBlock).toContain('href="/pos"');
  const launchOptions = existsSync(chromium.executablePath()) ? {} : { channel: "chrome" };
  const browser = await chromium.launch({ ...launchOptions, headless: true });
  const page = await browser.newPage();
  try {
    await page.clock.install();
    await page.setContent(`
      <button id="dashboardPrivacyBtn" aria-pressed="false"><i class="fas fa-eye"></i></button>
      <div id="salesCard" class="finora-stat-card">
        <div id="finoraSalesValue" data-dashboard-private="true">****</div>
      </div>
      <div id="expensesCard" class="finora-wide-card">
        <div id="finoraExpensesValue" data-dashboard-private="true">****</div>
      </div>
    `);
    await page.addScriptTag({ content: privacyScript });

    await page.evaluate(() => {
      setText("finoraSalesValue", "149,898,850 د.ع");
      setText("finoraExpensesValue", "9,961,501 د.ع");
    });
    await expect(page.locator("#finoraSalesValue")).toHaveText("****");
    await expect(page.locator("#finoraExpensesValue")).toHaveText("****");

    await page.evaluate(() => {
      setDashboardCardHoverState(document.getElementById("salesCard"), true);
    });
    await expect(page.locator("#finoraSalesValue")).toHaveText("149,898,850 د.ع");
    await expect(page.locator("#finoraExpensesValue")).toHaveText("****");
    await page.evaluate(() => {
      setDashboardCardHoverState(document.getElementById("salesCard"), false);
    });
    await expect(page.locator("#finoraSalesValue")).toHaveText("****");

    await page.evaluate(() => toggleDashboardPrivateValues());
    await expect(page.locator("#finoraSalesValue")).toHaveText("149,898,850 د.ع");
    await expect(page.locator("#dashboardPrivacyBtn")).toHaveAttribute("aria-pressed", "true");

    await page.clock.fastForward(30001);
    await expect(page.locator("#finoraSalesValue")).toHaveText("****");
    await expect(page.locator("#finoraExpensesValue")).toHaveText("****");
    await expect(page.locator("#dashboardPrivacyBtn")).toHaveAttribute("aria-pressed", "false");
  } finally {
    await browser.close();
  }
});
