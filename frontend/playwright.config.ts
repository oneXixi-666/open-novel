import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: {
    timeout: 8_000
  },
  use: {
    baseURL: "http://127.0.0.1:5273",
    trace: "on-first-retry"
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ],
  webServer: [
    {
      command: "../.venv/bin/python ../scripts/e2e_ai_provider.py",
      url: "http://127.0.0.1:8876/health",
      reuseExistingServer: false,
      timeout: 30_000
    },
    {
      command: "node scripts/e2e-backend-supervisor.mjs",
      url: "http://127.0.0.1:8875/health",
      reuseExistingServer: false,
      timeout: 30_000
    },
    {
      command: "VITE_WORKBENCH_API_BASE=http://127.0.0.1:8875 npm run dev -- --port 5273",
      url: "http://127.0.0.1:5273",
      reuseExistingServer: false,
      timeout: 30_000
    }
  ]
});
