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


async function mockDashboard(page, options = {}) {
  const dataBySymbol = options.dataBySymbol || {
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
      body: JSON.stringify({ symbols: Object.keys(dataBySymbol) })
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
        max_drawdown_1y_pct: -15.0,
        ...(options.analyticsBySymbol?.[symbol] || {})
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


async function configureDashboard(page, options) {
  await page.unroute("https://cdn.jsdelivr.net/**");
  await page.unroute("**/symbols");
  await page.unroute("**/analytics/*/series");
  await page.unroute("**/analytics/*");
  await page.unroute("**/latest/*");
  await mockDashboard(page, options);
}


test.beforeEach(async ({ page }) => {
  await mockDashboard(page);
  await page.goto("/login");
  await page.locator("#username").fill("test-user");
  await page.locator("#password").fill("test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
});


test("authentication protects browser resources and supports login and logout", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
    "content",
    "noindex, nofollow, noarchive"
  );

  await page.locator("#username").fill("test-user");
  await page.locator("#password").fill("incorrect");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid username or password.");

  await page.locator("#username").fill("test-user");
  await page.locator("#password").fill("test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/app.js");
  await expect(page).toHaveURL(/\/login$/);
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


test("desktop workspace separates statistics from the sticky visualization panel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator("#statusMessage")).toContainText("Showing latest stored data for TEST");

  const layout = await page.evaluate(() => {
    const box = selector => {
      const rect = document.querySelector(selector).getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, width: rect.width };
    };
    return {
      workspaceColumns: getComputedStyle(document.querySelector(".dashboard-workspace")).gridTemplateColumns.split(" ").length,
      returnsColumns: getComputedStyle(document.querySelector(".context-metrics-grid")).gridTemplateColumns.split(" ").length,
      metricsColumns: getComputedStyle(document.querySelector(".market-metrics-grid")).gridTemplateColumns.split(" ").length,
      visualizationPosition: getComputedStyle(document.querySelector(".visualization-column")).position,
      statistics: box(".statistics-column"),
      visualization: box(".visualization-column"),
      selector: box(".selector-card"),
      chart: box(".chart-card"),
      price: box(".price-card"),
      chartHeight: document.querySelector(".price-chart-container").getBoundingClientRect().height,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth
    };
  });

  expect(layout.workspaceColumns).toBe(2);
  expect(layout.returnsColumns).toBe(2);
  expect(layout.metricsColumns).toBe(2);
  expect(layout.statistics.width).toBeLessThan(layout.visualization.width);
  expect(layout.selector.left).toBeGreaterThan(layout.price.right);
  expect(layout.chart.left).toBeGreaterThan(layout.price.right);
  expect(layout.selector.top).toBeLessThan(layout.chart.top);
  expect(layout.visualizationPosition).toBe("sticky");
  expect(layout.chartHeight).toBeGreaterThanOrEqual(400);
  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
  await page.screenshot({ path: "test-results/dashboard-desktop.png", fullPage: true });
});


test("single-column workspace preserves dashboard reading order on tablet and phone", async ({ page }) => {
  const viewports = [
    { name: "tablet", width: 768, height: 1024, returns: 2, metrics: 2, priceHeight: [280, 320] },
    { name: "phone", width: 390, height: 844, returns: 1, metrics: 1, priceHeight: [240, 280] }
  ];

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.locator("#statusMessage")).toContainText("Showing latest stored data for TEST");

    const layout = await page.evaluate(() => {
      const columns = selector => getComputedStyle(document.querySelector(selector)).gridTemplateColumns.split(" ").length;
      const chartHeight = document.querySelector(".price-chart-container").getBoundingClientRect().height;
      const positions = [
        ".selector-card",
        ".price-card",
        ".metrics-grid",
        ".chart-card",
        ".context-card",
        '[aria-labelledby="returnsTitle"]',
        '[aria-labelledby="marketMetricsTitle"]'
      ].map(selector => document.querySelector(selector).getBoundingClientRect().top);
      return {
        returns: columns(".context-metrics-grid"),
        metrics: columns(".market-metrics-grid"),
        chartHeight,
        positions,
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth
      };
    });

    expect(layout.returns).toBe(viewport.returns);
    expect(layout.metrics).toBe(viewport.metrics);
    expect(layout.chartHeight).toBeGreaterThanOrEqual(viewport.priceHeight[0]);
    expect(layout.chartHeight).toBeLessThanOrEqual(viewport.priceHeight[1]);
    expect(layout.positions.every((top, index) => index === 0 || top > layout.positions[index - 1])).toBe(true);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
    await page.screenshot({ path: `test-results/dashboard-${viewport.name}.png`, fullPage: true });
  }
});


test("headline price remains fully visible for large formatted values", async ({ page }) => {
  const values = [
    { value: 9.99, formatted: "$9.99" },
    { value: 488.40, formatted: "$488.40" },
    { value: 1234.56, formatted: "$1,234.56" },
    { value: 99999.99, formatted: "$99,999.99" }
  ];
  const viewports = [
    { name: "desktop", width: 1440, height: 1000 },
    { name: "tablet", width: 768, height: 1024 },
    { name: "phone", width: 390, height: 844 }
  ];

  for (const price of values) {
    const series = buildSeries();
    series[series.length - 2].Close = price.value - 1;
    series[series.length - 1].Close = price.value;
    await configureDashboard(page, {
      dataBySymbol: { TEST: series },
      analyticsBySymbol: { TEST: { latest_close: price.value } }
    });

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await expect(page.locator("#latestPrice")).toHaveText(price.formatted);

      const layout = await page.evaluate(() => {
        const card = document.querySelector(".price-card").getBoundingClientRect();
        const price = document.querySelector("#latestPrice").getBoundingClientRect();
        return {
          card,
          price,
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth
        };
      });

      expect(layout.price.left).toBeGreaterThanOrEqual(layout.card.left);
      expect(layout.price.right).toBeLessThanOrEqual(layout.card.right);
      expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);

      if (price.value === 1234.56 && viewport.name === "desktop") {
        await page.screenshot({ path: "test-results/headline-price-desktop-1234.png", fullPage: true });
      }
    }
  }
});


test("daily change, neutral chips, range bar, and SMA comparisons handle values and nulls", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#dailyChange")).toHaveText("+$1.00 · +0.50%");
  await expect(page.locator("#dailyChange")).toHaveClass(/positive/);
  await expect(page.locator("#contextChips")).toContainText("+2.00% this month");
  await expect(page.locator("#contextChips")).toContainText("Above SMA 200");
  await expect(page.locator("#rangeMarker")).toHaveAttribute("style", /left: 66\.67%/);
  await expect(page.locator("#rangeDescription")).toContainText("Current position 66.67%");
  await expect(page.locator("#sma20Relation")).toHaveText("Price above SMA");

  const flatSeries = buildSeries();
  flatSeries[flatSeries.length - 2].Close = 400;
  flatSeries[flatSeries.length - 1].Close = 400;
  await configureDashboard(page, {
    dataBySymbol: { TEST: flatSeries },
    analyticsBySymbol: {
      TEST: {
        latest_close: 400,
        return_1d_pct: 0,
        return_1m_pct: null,
        range_position_52w_pct: null,
        low_52w: null,
        high_52w: null,
        sma_20: 400,
        sma_50: 400,
        sma_200: null,
        volume_vs_average_20d_pct: null
      }
    }
  });
  await page.goto("/");
  await expect(page.locator("#dailyChange")).toHaveText("$0.00 · 0.00%");
  await expect(page.locator("#dailyChange")).toHaveClass(/neutral/);
  await expect(page.locator("#contextChips .context-chip")).toHaveCount(0);
  await expect(page.locator(".range-position")).toHaveClass(/is-unavailable/);
  await expect(page.locator("#rangeDescription")).toContainText("unavailable");
  await expect(page.locator("#sma20Relation")).toHaveText("At SMA (within 0.1%)");
});


test("negative and unavailable daily changes remain explicit without color", async ({ page }) => {
  const negativeSeries = buildSeries();
  negativeSeries[negativeSeries.length - 2].Close = 402;
  negativeSeries[negativeSeries.length - 1].Close = 400;
  await configureDashboard(page, {
    dataBySymbol: { TEST: negativeSeries },
    analyticsBySymbol: { TEST: { latest_close: 400, return_1d_pct: -0.5 } }
  });
  await page.goto("/");
  await expect(page.locator("#dailyChange")).toHaveText("−$2.00 · −0.50%");
  await expect(page.locator("#dailyChange")).toHaveClass(/negative/);

  await configureDashboard(page, {
    dataBySymbol: { TEST: [negativeSeries.at(-1)] },
    analyticsBySymbol: { TEST: { latest_close: 400, return_1d_pct: null } }
  });
  await page.goto("/");
  await expect(page.locator("#dailyChange")).toHaveText("Daily change unavailable");
});


test("SMA chips retain keyboard checkbox semantics and chart lifecycle", async ({ page }) => {
  await page.goto("/");
  const sma200 = page.locator('[data-sma="SMA200"]');
  await sma200.focus();
  await page.keyboard.press("Space");
  await expect(sma200).toBeChecked();
  await expect(sma200.locator("xpath=..")).toHaveClass(/sma-chip/);
  const state = await page.evaluate(() => ({
    chartCount: window.__chartInstances.length,
    previousChartsDestroyed: window.__chartInstances.slice(-4, -2).every(chart => chart.destroyed),
    chartHeight: document.querySelector(".price-chart-container").getBoundingClientRect().height,
    closeWidth: window.__chartInstances.at(-2).config.data.datasets[0].borderWidth
  }));
  expect(state.chartCount).toBe(4);
  expect(state.previousChartsDestroyed).toBe(true);
  expect(state.chartHeight).toBeGreaterThanOrEqual(320);
  expect(state.closeWidth).toBe(3);
});
