const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./frontend-tests",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4174",
    browserName: "chromium",
    headless: true
  },
  webServer: {
    command: "python3 -m uvicorn backend.app.api:app --host 127.0.0.1 --port 4174",
    url: "http://127.0.0.1:4174",
    reuseExistingServer: false,
    env: {
      AUTH_USERNAME: "test-user",
      AUTH_PASSWORD_HASH: "scrypt$16384$8$1$MDEyMzQ1Njc4OWFiY2RlZg$P7LO0VyeojNF-PzPS0VF4tYr0K5xxUzsk6qRsYZmqd0",
      SESSION_SECRET: "browser-test-session-secret-at-least-32-bytes"
    }
  }
});
