import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e-settings",
  workers: 1,
  timeout: 90_000,
  use: {
    baseURL: "http://localhost:5176",
    channel: "msedge",
    headless: true,
    viewport: { width: 1440, height: 900 },
    locale: "ar",
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
  },
  webServer: {
    command: "npx vite --port 5176 --strictPort",
    port: 5176,
    reuseExistingServer: false,
    env: { VITE_FINORA_SOURCE: "http", VITE_FINORA_API_URL: "http://127.0.0.1:5019" },
  },
});
