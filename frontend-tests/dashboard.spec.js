const { test, expect } = require("@playwright/test");


function buildSeries(endDate = "2025-01-31", count = 300) {
  const end = new Date(`${endDate}T00:00:00`);
  const rows = [];
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    const date = new Date(end);
    date.setDate(date.getDate() - offset);
    const index = count - offset;
    rows.push({
      Date: date.toISOString().slice(0, 10),
      Close: 100 + index,
      Volume: 1_000 + index,
      SMA20: index >= 20 ? 90 + index : null,
      SMA50: index >= 50 ? 75 + index : null,
      SMA200: index >= 200 ? index : null,
      DailyReturnPct: index > 1 ? 0.5 : null
    });
  }
  return rows;
}


async function mockDashboard(page) {
  const dataBySymbol = {
    TEST: buildSeries(),
    NEXT: buildSeries("2025-02-28", 300)
  };

  await page.route("https://cdn.jsdelivr.net/**", route => route.fulfill({
    contentType: "application/javascript",
    body: `
      window.__chartInstances = [];
      window.Chart = class {
        constructor(canvas, config) {
          this.canvas = canvas;
          this.config = config;
          this.destroyed = false;
          window.__chartInstances.push(this);
        }
        destroy() { this.destroyed = true; }
      };
    `
  }));

  await page.route("**/symbols", route => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ symbols: ["TEST", "NEXT"] })
  }));
  await page.route("**/analytics/*/series", route => {
    const symbol = route.request().url().split("/").at(-2);
    const rows = dataBySymbol[symbol];
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        symbol,
        as_of_date: rows.at(-1).Date,
        count: rows.length,
        data: rows
      })
    });
  });
  await page.route("**/analytics/*", route => {
    const symbol = route.request().url().split("/").at(-1);
    const rows = dataBySymbol[symbol];
    const latest = rows.at(-1);
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        symbol,
        date: latest.Date,
        as_of_date: latest.Date,
        latest_data_date: latest.Date,
        latest_data_timestamp: `${latest.Date} 00:00:00`,
        latest_close: latest.Close,
        sma_20: latest.SMA20,
        sma_50: latest.SMA50,
        sma_200: latest.SMA200,
        return_1d_pct: 0.5,
        return_1w_pct: 1.0,
        return_1m_pct: 2.0,
        return_3m_pct: 3.0,
        return_ytd_pct: 4.0,
        return_1y_pct: 5.0,
        high_52w: latest.Close + 10,
        low_52w: latest.Close - 20,
        range_position_52w_pct: 66.67,
        current_volume: latest.Volume,
        average_volume_20d: latest.Volume - 20,
        volume_vs_average_20d_pct: 2.0,
        annualized_volatility_30d_pct: 12.0,
        max_drawdown_1y_pct: -15.0
      })
    });
  });
  await page.route("**/latest/*", route => {
    const symbol = route.request().url().split("/").at(-1);
    const latest = dataBySymbol[symbol].at(-1);
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        Symbol: symbol,
        Date: latest.Date,
        Open: latest.Close - 1,
        High: latest.Close + 2,
        Low: latest.Close - 2,
        Close: latest.Close,
        Volume: latest.Volume
      })
    });
  });
}


test.beforeEach(async ({ page }) => {
  await mockDashboard(page);
});


test("range, SMA, chart synchronization, and replacement behavior", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#statusMessage")).toContainText("Showing latest stored data for TEST");

  await expect(page.locator('[data-range="1Y"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-range][aria-pressed="true"]')).toHaveCount(1);
  await page.locator('[data-range="1M"]').click();
  await expect(page.locator('[data-range="1M"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-range="1Y"]')).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator('[data-range][aria-pressed="true"]')).toHaveCount(1);

  let chartState = await page.evaluate(() => ({
    count: window.__chartInstances.length,
    destroyed: window.__chartInstances.slice(0, -2).map(chart => chart.destroyed),
    priceLabels: window.__chartInstances.at(-2).config.data.labels,
    volumeLabels: window.__chartInstances.at(-1).config.data.labels,
    priceLengths: window.__chartInstances.at(-2).config.data.datasets.map(dataset => dataset.data.length),
    volumeLength: window.__chartInstances.at(-1).config.data.datasets[0].data.length
  }));
  expect(chartState.count).toBe(4);
  expect(chartState.destroyed).toEqual([true, true]);
  expect(chartState.priceLabels).toEqual(chartState.volumeLabels);
  expect(chartState.priceLengths.every(length => length === chartState.volumeLength)).toBe(true);
  expect(chartState.priceLabels.at(-1)).toBe("2025-01-31");

  await page.locator('[data-sma="SMA200"]').check();
  await expect(page.locator('[data-sma="SMA200"]')).toBeChecked();
  await expect(page.locator("#chartDescription")).toContainText("SMA 200");
  chartState = await page.evaluate(() => ({
    count: window.__chartInstances.length,
    priorDestroyed: window.__chartInstances.slice(-4, -2).map(chart => chart.destroyed)
  }));
  expect(chartState.count).toBe(6);
  expect(chartState.priorDestroyed).toEqual([true, true]);

  await page.locator("#stockSelect").selectOption("NEXT");
  await expect(page.locator("#statusMessage")).toContainText("NEXT");
  await expect(page.locator("#latestTimestamp")).toHaveText("Latest daily data: 2025-02-28");
  await expect(page.locator("#dateValue")).toHaveText("2025-02-28");
  await expect(page.locator("#chartDescription")).toContainText("NEXT, 1M period");
  await expect(page.locator("#chartDescription")).toContainText("2025-02-28");
  await expect(page.locator("#stockChart")).toHaveAttribute("aria-label", /NEXT.*1M/);
  await expect(page.locator("#volumeChart")).toHaveAttribute("aria-label", /NEXT.*1M/);

  const replacement = await page.evaluate(() => ({
    oldDestroyed: window.__chartInstances.slice(-4, -2).map(chart => chart.destroyed),
    priceLabels: window.__chartInstances.at(-2).config.data.labels,
    volumeLabels: window.__chartInstances.at(-1).config.data.labels
  }));
  expect(replacement.oldDestroyed).toEqual([true, true]);
  expect(replacement.priceLabels).toEqual(replacement.volumeLabels);
  expect(replacement.priceLabels.at(-1)).toBe("2025-02-28");
});


test("phone layout has no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(page.locator("#statusMessage")).toContainText("Showing latest stored data for TEST");

  const layout = await page.evaluate(() => {
    const selectors = [
      ".container",
      ".selector-card",
      ".metric-card",
      ".chart-card",
      ".chart-controls",
      ".range-controls",
      ".sma-controls",
      ".price-chart-container",
      ".volume-chart-container"
    ];
    const offenders = Array.from(document.querySelectorAll(selectors.join(",")))
      .filter(element => {
        const rect = element.getBoundingClientRect();
        return rect.left < -1 || rect.right > window.innerWidth + 1;
      })
      .map(element => ({ className: element.className, id: element.id }));
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      offenders
    };
  });

  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
  expect(layout.offenders).toEqual([]);
});
