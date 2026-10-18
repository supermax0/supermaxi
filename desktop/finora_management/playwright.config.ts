import { defineConfig } from "@playwright/test";

/** Drives the built Electron app (run `npm run build` first). */
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { trace: "retain-on-failure" },
});
