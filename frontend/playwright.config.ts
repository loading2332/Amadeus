import { defineConfig, devices } from "@playwright/test";

const python = process.platform === "win32"
  ? '"..\\.venv\\Scripts\\python.exe"'
  : '"../.venv/bin/python"';

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `${python} e2e/server.py`,
      url: "http://127.0.0.1:18001/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
      env: { ...process.env, AMADEUS_E2E_PORT: "18001" },
    },
    {
      command: "pnpm run dev --host 127.0.0.1 --port 4173",
      url: "http://127.0.0.1:4173/static/",
      reuseExistingServer: !process.env.CI,
      env: { ...process.env, AMADEUS_API_TARGET: "http://127.0.0.1:18001" },
    },
  ],
});
