import { defineConfig, devices } from "@playwright/test";

// Smoke tests drive the production build (`npm run build` first) with every /api call mocked in the
// browser, so they need no backend. An /api call a test doesn't mock fails the test (see e2e/api.ts).
const PORT = Number(process.env.E2E_PORT ?? 3917);

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // `next start` warns that the build is standalone (for Docker), but serves it, which is all we need.
    command: `npm run start -- --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/login`,
    reuseExistingServer: false,   // never test whatever else happens to be on the port
    timeout: 60_000,
  },
});
