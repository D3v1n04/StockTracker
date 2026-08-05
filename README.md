# StockTracker

StockTracker is a full-stack stock market dashboard that downloads historical
price data from Yahoo Finance, stores it locally in SQLite, and exposes the
stored data and calculated metrics through a FastAPI REST API. A lightweight
HTML, CSS, and JavaScript frontend provides stock selection, latest market
information, and an interactive price history chart.

## Features

- Downloads historical stock data from Yahoo Finance
- Stores historical price data in SQLite
- Provides a REST API built with FastAPI
- Includes a responsive frontend dashboard
- Supports interactive stock selection
- Displays the latest open, high, low, close, volume, and date values
- Charts historical closing prices with Chart.js
- Calculates stock metrics through a Pandas-based analytics engine

## Tech Stack

### Backend

- Python
- FastAPI
- SQLite
- Pandas

### Frontend

- HTML
- CSS
- JavaScript
- Chart.js

### Data Source

- Yahoo Finance, accessed through `yfinance`

## Project Architecture

```text
Yahoo Finance
      │
      ▼
market_data.py
      │
      ▼
SQLite Database
      │
      ▼
data_access.py
      │
      ▼
analytics.py
      │
      ▼
FastAPI
      │
      ▼
Frontend Dashboard
```

`market_data.py` handles data collection and persistence. `data_access.py`
contains the database queries used by the application. Raw API routes can read
through the data access layer directly, while analytics routes pass the stored
history through `analytics.py` before returning calculated results.

## Project Structure

```text
StockTracker/
├── backend/
│   └── app/
│       ├── analytics.py      # Analytics and time-series calculations
│       ├── api.py            # FastAPI application and routes
│       ├── data_access.py    # SQLite initialization, reads, and writes
│       └── market_data.py    # Yahoo Finance data download workflow
├── data/
│   └── market_data.db        # Local SQLite database
├── frontend/
│   ├── app.js                # API calls and dashboard behavior
│   ├── index.html            # Dashboard markup
│   └── style.css             # Dashboard styles
└── README.md
```

## Analytics

The API separates stored historical records from computed analytics:

- **Raw historical data endpoints** return values stored in SQLite. These
  include the full history from `GET /stocks/{symbol}` and the most recent
  record from `GET /latest/{symbol}`.
- **Computed analytics endpoints** load historical records and use Pandas to
  calculate summary metrics or an enriched time series. These are available
  from `GET /analytics/{symbol}` and `GET /analytics/{symbol}/series`.

`analytics.py` acts as the business logic layer between the API and the
database for analytics requests. It obtains historical data through
`data_access.py`, performs the calculations, and returns API-ready results.

The currently implemented analytics are:

- 20-day Simple Moving Average (SMA20)
- 50-day Simple Moving Average (SMA50)
- Daily percentage return
- Annualized historical volatility, calculated from daily returns using 252
  trading days

The analytics summary endpoint returns the latest SMA20, SMA50, daily return,
and annualized volatility values. The analytics series endpoint returns close,
SMA20, SMA50, and daily return values for each available date.

## API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | Checks whether the API is running |
| `GET` | `/symbols` | Lists symbols currently stored in SQLite |
| `GET` | `/stocks/{symbol}` | Returns stored historical OHLCV data |
| `GET` | `/latest/{symbol}` | Returns the latest stored OHLCV record |
| `GET` | `/analytics/{symbol}` | Returns the latest computed analytics summary |
| `GET` | `/analytics/{symbol}/series` | Returns the computed analytics time series |

## Setup

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows, activate it with:

```powershell
.venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install fastapi uvicorn pandas yfinance
```

### 3. Download market data

From the project root, run:

```bash
python backend/app/market_data.py
```

This initializes `data/market_data.db` if needed and downloads one year of
history for the symbols configured in `TRACKED_SYMBOLS`.

### 4. Start the API

```bash
uvicorn backend.app.api:app --reload
```

The API is available at `http://127.0.0.1:8000`. FastAPI's interactive API
documentation is available at `http://127.0.0.1:8000/docs`.

### 5. Start the frontend

In a second terminal, serve the frontend on port 3000:

```bash
python -m http.server 3000 --directory frontend
```

Open `http://127.0.0.1:3000` in a browser. The API CORS configuration permits
the frontend origins `http://127.0.0.1:3000` and `http://localhost:3000`.

## Future Roadmap

- Relative Strength Index (RSI)
- Moving Average Convergence Divergence (MACD)
- Bollinger Bands
- Portfolio tracking
- Background data updates
- C++ analytics engine integration
