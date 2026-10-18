import { defineConfig } from "@playwright/test";

/** Web-shell E2E for FINORA CORE (development data). Uses the installed Microsoft Edge. */
export default defineConfig({
  testDir: "e2e",
  timeout: 40_000,
  expect: { timeout: 8_000, toHaveScreenshot: { maxDiffPixelRatio: 0.01 } },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  snapshotPathTemplate: "e2e/__screenshots__/{arg}{ext}",
  use: {
    baseURL: "http://localhost:5174",
    channel: "msedge",
    headless: true,
    viewport: { width: 1440, height: 900 },
    locale: "ar",
  },
  webServer: {
    command: "npm run dev",
    port: 5174,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
