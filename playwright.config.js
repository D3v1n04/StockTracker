const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./frontend-tests",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true
  },
  webServer: {
    command: "python3 -m http.server 4173 --directory frontend",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false
  }
});
