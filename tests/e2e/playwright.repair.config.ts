import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./repair-tests",
  workers: 1,
  retries: 0,
  timeout: 60000,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.REPAIR_UI_URL ?? "http://127.0.0.1:3011",
    channel: process.env.REPAIR_BROWSER_CHANNEL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  outputDir: "../../.tools/repair-browser-artifacts",
  reporter: "list",
});
