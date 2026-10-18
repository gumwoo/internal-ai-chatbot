import { defineConfig } from "@playwright/test";

// T-20/21 브라우저 E2E. 백엔드는 규칙 기반 가짜 모델(과금 없음)·시험 DB·실제 세션으로 띄운다.
export default defineConfig({
  testDir: "e2e",
  workers: 1,
  timeout: 60_000,
  retries: 0,
  reporter: [["list"]],
  outputDir: process.env.E2E_RESULTS_DIR ?? "test-results",
  use: {
    baseURL: "http://127.0.0.1:5190",
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "chrome",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run python -m tests.e2e_server",
      cwd: "../backend",
      url: "http://127.0.0.1:8011/api/v1/health/live",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { PYTHONIOENCODING: "utf-8" },
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5190",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { API_ORIGIN: "http://127.0.0.1:8011" },
    },
  ],
});
