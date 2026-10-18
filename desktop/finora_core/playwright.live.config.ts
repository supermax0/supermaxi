import { defineConfig } from "@playwright/test";

/**
 * Live E2E: the desktop web shell against a REAL local FINORA server (Phase 6).
 * Prerequisites (see TESTING section in README):
 *   py scripts/provision_finora_core_e2e.py setup <creds.json>
 *   FINORA_CORE_HOUSE_TENANT=fc-e2e-house FINORA_CORE_DEV_LOOPBACK=1 FINORA_ENV=development FLASK_PORT=5018 python app.py
 *   FC_E2E_CREDS=<creds.json> npx playwright test -c playwright.live.config.ts
 */
const API = process.env.FC_E2E_API ?? "http://127.0.0.1:5018";

export default defineConfig({
  testDir: "e2e-live",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5175",
    channel: "msedge",
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npx vite --port 5175 --strictPort",
    port: 5175,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { VITE_FINORA_SOURCE: "http", VITE_FINORA_API_URL: API },
  },
});
