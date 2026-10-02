import { defineConfig, devices } from "@playwright/test";

// Smoke test of the built app with the API mocked in the browser: offline and
// deterministic, and separate from the Python unit suite (it needs a browser).
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:4173", serviceWorkers: "block", trace: "retain-on-failure" },
  webServer: { command: "npm run build && npm run preview", url: "http://127.0.0.1:4173", reuseExistingServer: true },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
});
