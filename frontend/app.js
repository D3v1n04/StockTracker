const API_BASE_URL = "http://127.0.0.1:8000";

const stockSelect = document.getElementById("stockSelect");
const stockTitle = document.getElementById("stockTitle");
const latestPrice = document.getElementById("latestPrice");
const statusMessage = document.getElementById("statusMessage");
const chartTitle = document.getElementById("chartTitle");
const chartCanvas = document.getElementById("stockChart");

const metricFields = {
  Open: document.getElementById("openValue"),
  High: document.getElementById("highValue"),
  Low: document.getElementById("lowValue"),
  Close: document.getElementById("closeValue"),
  Volume: document.getElementById("volumeValue"),
  Date: document.getElementById("dateValue")
};

let stockChart = null;

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD"
});

const numberFormatter = new Intl.NumberFormat("en-US");

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
  return typeof value === "number" ? currencyFormatter.format(value) : "--";
}

function formatNumber(value) {
  return typeof value === "number" ? numberFormatter.format(value) : "--";
}

function resetDashboard(message) {
  stockTitle.textContent = message;
  latestPrice.textContent = "--";
  chartTitle.textContent = "Price trend";

  Object.values(metricFields).forEach(element => {
    element.textContent = "--";
  });

  if (stockChart !== null) {
    stockChart.destroy();
    stockChart = null;
  }
}

async function loadSymbols() {
  setLoading(true);
  setStatus("Loading available stocks...");

  try {
    const data = await fetchJson(`${API_BASE_URL}/symbols`);
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
    const [historyData, latestData] = await Promise.all([
      fetchJson(`${API_BASE_URL}/stocks/${symbol}`),
      fetchJson(`${API_BASE_URL}/latest/${symbol}`)
    ]);

    if (latestData.error) {
      throw new Error(latestData.error);
    }

    const prices = Array.isArray(historyData.data) ? historyData.data : [];

    updateSummary(symbol, latestData);
    drawChart(symbol, prices);
    setStatus(`Showing latest data for ${symbol}.`);
  } catch (error) {
    resetDashboard(`Unable to load ${symbol}`);
    setStatus(`Could not load ${symbol}. ${error.message}`, true);
  } finally {
    setLoading(false);
  }
}

function updateSummary(symbol, latestData) {
  stockTitle.textContent = `${symbol} Stock Price`;
  latestPrice.textContent = formatCurrency(latestData.Close);

  metricFields.Open.textContent = formatCurrency(latestData.Open);
  metricFields.High.textContent = formatCurrency(latestData.High);
  metricFields.Low.textContent = formatCurrency(latestData.Low);
  metricFields.Close.textContent = formatCurrency(latestData.Close);
  metricFields.Volume.textContent = formatNumber(latestData.Volume);
  metricFields.Date.textContent = latestData.Date || "--";
}

function drawChart(symbol, prices) {
  const labels = prices.map(row => row.Date);
  const closePrices = prices.map(row => row.Close);

  chartTitle.textContent = `${symbol} close price trend`;

  if (stockChart !== null) {
    stockChart.destroy();
  }

  stockChart = new Chart(chartCanvas, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: `${symbol} Close`,
          data: closePrices,
          borderColor: "#0f766e",
          backgroundColor: "rgba(15, 118, 110, 0.12)",
          borderWidth: 3,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: "#0f766e",
          tension: 0.25
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: "index"
      },
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          callbacks: {
            label: context => `Close: ${formatCurrency(context.parsed.y)}`
          }
        }
      },
      scales: {
        x: {
          grid: {
            display: false
          },
          ticks: {
            maxTicksLimit: 8,
            color: "#64748b"
          }
        },
        y: {
          grid: {
            color: "#e2e8f0"
          },
          ticks: {
            color: "#64748b",
            callback: value => formatCurrency(value)
          }
        }
      }
    }
  });
}

stockSelect.addEventListener("change", () => {
  loadStock(stockSelect.value);
});

loadSymbols();
