const stockSelect = document.getElementById("stockSelect");
const stockTitle = document.getElementById("stockTitle");
const latestPrice = document.getElementById("latestPrice");
const latestTimestamp = document.getElementById("latestTimestamp");
const statusMessage = document.getElementById("statusMessage");
const contextSummary = document.getElementById("contextSummary");
const chartTitle = document.getElementById("chartTitle");
const chartSubtitle = document.getElementById("chartSubtitle");
const chartDescription = document.getElementById("chartDescription");
const chartCanvas = document.getElementById("stockChart");
const volumeCanvas = document.getElementById("volumeChart");
const rangeButtons = Array.from(document.querySelectorAll("[data-range]"));
const smaToggles = Array.from(document.querySelectorAll("[data-sma]"));

const metricFields = {
  Open: document.getElementById("openValue"),
  High: document.getElementById("highValue"),
  Low: document.getElementById("lowValue"),
  Close: document.getElementById("closeValue"),
  Volume: document.getElementById("volumeValue"),
  Date: document.getElementById("dateValue")
};

const analyticsFields = {
  return_1d_pct: document.getElementById("return1d"),
  return_1w_pct: document.getElementById("return1w"),
  return_1m_pct: document.getElementById("return1m"),
  return_3m_pct: document.getElementById("return3m"),
  return_ytd_pct: document.getElementById("returnYtd"),
  return_1y_pct: document.getElementById("return1y"),
  range_position_52w_pct: document.getElementById("rangePosition"),
  volume_vs_average_20d_pct: document.getElementById("volumeComparison"),
  sma_20: document.getElementById("sma20Value"),
  sma_50: document.getElementById("sma50Value"),
  sma_200: document.getElementById("sma200Value"),
  annualized_volatility_30d_pct: document.getElementById("volatility30"),
  max_drawdown_1y_pct: document.getElementById("maxDrawdown")
};

let stockChart = null;
let volumeChart = null;
let currentSymbol = "";
let currentSeries = [];
let activeRange = "1Y";

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD"
});
const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}

function setStatus(message, isError = false) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
}

function setLoading(isLoading) {
  document.body.classList.toggle("is-loading", isLoading);
  stockSelect.disabled = isLoading;
}

function formatCurrency(value) {
  return Number.isFinite(value) ? currencyFormatter.format(value) : "—";
}

function formatNumber(value) {
  return Number.isFinite(value) ? numberFormatter.format(value) : "—";
}

function formatPercentage(value, signed = true) {
  if (!Number.isFinite(value)) {
    return "—";
  }
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatDate(value) {
  return typeof value === "string" ? value.split(/[ T]/)[0] : "—";
}

function destroyCharts() {
  if (stockChart !== null) {
    stockChart.destroy();
    stockChart = null;
  }
  if (volumeChart !== null) {
    volumeChart.destroy();
    volumeChart = null;
  }
}

function resetDashboard(message) {
  stockTitle.textContent = message;
  latestPrice.textContent = "—";
  latestTimestamp.textContent = "Latest daily data: —";
  chartTitle.textContent = "Price trend";
  chartSubtitle.textContent = "Closing price and selected moving averages";
  contextSummary.textContent = "Market context is unavailable for this symbol.";
  chartDescription.textContent = "No chart data is available.";
  chartCanvas.setAttribute("aria-label", "Stock closing price and moving-average chart");
  volumeCanvas.setAttribute("aria-label", "Stock trading volume chart");

  [...Object.values(metricFields), ...Object.values(analyticsFields)].forEach(element => {
    element.textContent = "—";
  });
  document.getElementById("rangeValues").textContent = "Low — · High —";
  document.getElementById("averageVolume").textContent = "Average —";
  currentSeries = [];
  destroyCharts();
}

async function loadSymbols() {
  setLoading(true);
  setStatus("Loading available stocks...");

  try {
    const data = await fetchJson("/symbols");
    const symbols = Array.isArray(data.symbols) ? data.symbols : [];
    stockSelect.innerHTML = "";

    symbols.forEach(symbol => {
      const option = document.createElement("option");
      option.value = symbol;
      option.textContent = symbol;
      stockSelect.appendChild(option);
    });

    if (symbols.length === 0) {
      resetDashboard("No stocks available");
      setStatus("No symbols returned by the API.", true);
      return;
    }

    await loadStock(symbols[0]);
  } catch (error) {
    resetDashboard("Unable to load stocks");
    setStatus(`Could not load symbols. ${error.message}`, true);
  } finally {
    setLoading(false);
  }
}

async function loadStock(symbol) {
  setLoading(true);
  setStatus(`Loading ${symbol}...`);

  try {
    const [latestData, analyticsData, seriesData] = await Promise.all([
      fetchJson(`/latest/${symbol}`),
      fetchJson(`/analytics/${symbol}`),
      fetchJson(`/analytics/${symbol}/series`)
    ]);

    if (latestData.error || analyticsData.error || seriesData.error) {
      throw new Error(latestData.error || analyticsData.error || seriesData.error);
    }

    currentSymbol = symbol;
    currentSeries = Array.isArray(seriesData.data) ? seriesData.data : [];
    updateLatestSummary(symbol, latestData, analyticsData);
    updateMarketContext(symbol, analyticsData);
    drawCharts();
    setStatus(`Showing latest stored data for ${symbol}.`);
  } catch (error) {
    resetDashboard(`Unable to load ${symbol}`);
    setStatus(`Could not load ${symbol}. ${error.message}`, true);
  } finally {
    setLoading(false);
  }
}

function updateLatestSummary(symbol, latestData, analyticsData) {
  stockTitle.textContent = `${symbol} Stock Price`;
  latestPrice.textContent = formatCurrency(latestData.Close);
  const asOfDate = analyticsData.as_of_date || analyticsData.latest_data_date || latestData.Date;
  latestTimestamp.textContent = `Latest daily data: ${formatDate(asOfDate)}`;

  metricFields.Open.textContent = formatCurrency(latestData.Open);
  metricFields.High.textContent = formatCurrency(latestData.High);
  metricFields.Low.textContent = formatCurrency(latestData.Low);
  metricFields.Close.textContent = formatCurrency(latestData.Close);
  metricFields.Volume.textContent = formatNumber(latestData.Volume);
  metricFields.Date.textContent = formatDate(latestData.Date);
}

function updateMarketContext(symbol, metrics) {
  Object.entries(analyticsFields).forEach(([key, element]) => {
    if (["sma_20", "sma_50", "sma_200"].includes(key)) {
      element.textContent = formatCurrency(metrics[key]);
    } else if (["range_position_52w_pct", "annualized_volatility_30d_pct"].includes(key)) {
      element.textContent = formatPercentage(metrics[key], false);
    } else {
      element.textContent = formatPercentage(metrics[key]);
    }
  });

  document.getElementById("rangeValues").textContent =
    `Low ${formatCurrency(metrics.low_52w)} · High ${formatCurrency(metrics.high_52w)}`;
  document.getElementById("averageVolume").textContent =
    `Current ${formatNumber(metrics.current_volume)} · Average ${formatNumber(metrics.average_volume_20d)}`;

  const observations = [];
  if (Number.isFinite(metrics.return_1m_pct)) {
    if (metrics.return_1m_pct === 0) {
      observations.push(`${symbol} is unchanged over the past month.`);
    } else {
      const direction = metrics.return_1m_pct > 0 ? "up" : "down";
      observations.push(`${symbol} is ${direction} ${Math.abs(metrics.return_1m_pct).toFixed(2)}% over the past month.`);
    }
  }
  if (Number.isFinite(metrics.sma_50) && metrics.sma_50 !== 0 && Number.isFinite(metrics.latest_close)) {
    const distance = (metrics.latest_close / metrics.sma_50 - 1) * 100;
    const relation = distance >= 0 ? "above" : "below";
    observations.push(`The latest close is ${Math.abs(distance).toFixed(2)}% ${relation} its 50-day average.`);
  }
  if (Number.isFinite(metrics.volume_vs_average_20d_pct)) {
    const relation = metrics.volume_vs_average_20d_pct >= 0 ? "above" : "below";
    observations.push(`Latest volume is ${Math.abs(metrics.volume_vs_average_20d_pct).toFixed(1)}% ${relation} its prior 20-session average.`);
  }

  contextSummary.textContent = observations.length > 0
    ? observations.join(" ")
    : "There is not yet enough valid history to summarize recent price and volume context.";
}

function parseSeriesDate(value) {
  return new Date(`${formatDate(value)}T00:00:00`);
}

function subtractMonths(date, months) {
  const result = new Date(date);
  const targetDay = result.getDate();
  result.setDate(1);
  result.setMonth(result.getMonth() - months);
  const lastDay = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
  result.setDate(Math.min(targetDay, lastDay));
  return result;
}

function filteredSeries() {
  if (activeRange === "MAX" || currentSeries.length === 0) {
    return currentSeries;
  }

  const latestDate = parseSeriesDate(currentSeries[currentSeries.length - 1].Date);
  let cutoff;
  if (activeRange === "YTD") {
    cutoff = new Date(latestDate.getFullYear(), 0, 1);
  } else {
    const monthsByRange = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 };
    cutoff = subtractMonths(latestDate, monthsByRange[activeRange]);
  }
  return currentSeries.filter(row => parseSeriesDate(row.Date) >= cutoff);
}

function priceDataset(label, field, color, options = {}) {
  return {
    label,
    data: options.rows.map(row => row[field]),
    borderColor: color,
    backgroundColor: options.backgroundColor || color,
    borderWidth: options.borderWidth || 2,
    borderDash: options.borderDash || [],
    fill: options.fill || false,
    pointRadius: 0,
    pointHoverRadius: field === "Close" ? 5 : 3,
    spanGaps: false,
    tension: 0.2,
    hidden: options.hidden || false
  };
}

function drawCharts() {
  const rows = filteredSeries();
  const labels = rows.map(row => row.Date);
  const maxTicks = window.innerWidth <= 700 ? 5 : 10;
  const visibleSmas = Object.fromEntries(smaToggles.map(toggle => [toggle.dataset.sma, toggle.checked]));

  chartTitle.textContent = `${currentSymbol} price history`;
  chartSubtitle.textContent = `${activeRange} view · closing price and selected moving averages`;
  const firstDate = rows.length > 0 ? formatDate(rows[0].Date) : "unavailable";
  const lastDate = rows.length > 0 ? formatDate(rows[rows.length - 1].Date) : "unavailable";
  const latestVisibleClose = rows.length > 0 ? rows[rows.length - 1].Close : null;
  const selectedSmas = smaToggles
    .filter(toggle => toggle.checked)
    .map(toggle => toggle.dataset.sma.replace("SMA", "SMA "));
  const overlayDescription = selectedSmas.length > 0
    ? `${selectedSmas.join(", ")} overlays are shown.`
    : "No moving-average overlays are shown.";
  chartDescription.textContent = `${currentSymbol}, ${activeRange} period, ${firstDate} through ${lastDate}, ${rows.length} data points, latest close ${formatCurrency(latestVisibleClose)}. ${overlayDescription}`;
  chartCanvas.setAttribute(
    "aria-label",
    `${currentSymbol} closing price and moving-average chart for the ${activeRange} period`
  );
  volumeCanvas.setAttribute(
    "aria-label",
    `${currentSymbol} trading volume chart for the ${activeRange} period`
  );
  destroyCharts();

  stockChart = new Chart(chartCanvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        priceDataset(`${currentSymbol} Close`, "Close", "#0f766e", {
          rows,
          borderWidth: 3,
          fill: true,
          backgroundColor: "rgba(15, 118, 110, 0.10)"
        }),
        priceDataset("SMA 20", "SMA20", "#b7791f", { rows, borderDash: [7, 4], hidden: !visibleSmas.SMA20 }),
        priceDataset("SMA 50", "SMA50", "#475569", { rows, borderDash: [3, 4], hidden: !visibleSmas.SMA50 }),
        priceDataset("SMA 200", "SMA200", "#7c3aed", { rows, borderDash: [10, 4], hidden: !visibleSmas.SMA200 })
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: {
          display: true,
          position: "top",
          align: "start",
          onClick: () => {},
          labels: { color: "#475569", usePointStyle: true, boxWidth: 8, padding: 16 }
        },
        tooltip: {
          callbacks: {
            title: items => items.length > 0 ? `Date: ${formatDate(items[0].label)}` : "",
            label: context => `${context.dataset.label}: ${formatCurrency(context.parsed.y)}`
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            autoSkip: true,
            autoSkipPadding: 18,
            color: "#64748b",
            maxRotation: 35,
            minRotation: 0,
            maxTicksLimit: maxTicks,
            padding: 10,
            callback(value) { return formatDate(this.getLabelForValue(value)); }
          }
        },
        y: {
          grid: { color: "#e2e8f0" },
          ticks: { color: "#64748b", callback: value => formatCurrency(value) }
        }
      }
    }
  });

  volumeChart = new Chart(volumeCanvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Volume",
        data: rows.map(row => row.Volume),
        backgroundColor: "rgba(15, 118, 110, 0.38)",
        borderColor: "#0f766e",
        borderWidth: 1,
        barPercentage: 0.9,
        categoryPercentage: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => items.length > 0 ? `Date: ${formatDate(items[0].label)}` : "",
            label: context => `Volume: ${formatNumber(context.parsed.y)}`
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            autoSkip: true,
            autoSkipPadding: 18,
            color: "#64748b",
            maxRotation: 35,
            minRotation: 0,
            maxTicksLimit: maxTicks,
            padding: 8,
            callback(value) { return formatDate(this.getLabelForValue(value)); }
          }
        },
        y: {
          beginAtZero: true,
          grid: { color: "#e2e8f0" },
          ticks: { color: "#64748b", maxTicksLimit: 4, callback: value => numberFormatter.format(value) }
        }
      }
    }
  });
}

rangeButtons.forEach(button => {
  button.addEventListener("click", () => {
    activeRange = button.dataset.range;
    rangeButtons.forEach(item => {
      const isActive = item === button;
      item.classList.toggle("active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    });
    if (currentSeries.length > 0) {
      drawCharts();
    }
  });
});

smaToggles.forEach(toggle => {
  toggle.addEventListener("change", () => {
    if (currentSeries.length > 0) {
      drawCharts();
    }
  });
});

stockSelect.addEventListener("change", () => loadStock(stockSelect.value));
loadSymbols();
