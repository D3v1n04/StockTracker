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
- Displays the latest open, high, low, close, volume, and stored daily data date
- Charts historical closing prices, moving averages, and volume with Chart.js
- Filters the chart to 1M, 3M, 6M, YTD, 1Y, or the maximum stored range
- Summarizes recent returns, trend, trading range, volume, volatility, and drawdown
- Calculates stock metrics through a Pandas-based analytics engine
- Protects the single-user dashboard, assets, API, readiness, and API docs with
  a signed session cookie

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
├── alembic/                 # Versioned database schema migrations
├── backend/
│   └── app/
│       ├── analytics.py      # Analytics and time-series calculations
│       ├── api.py            # FastAPI application and routes
│       ├── data_access.py    # Shared database reads and writes
│       ├── database.py       # SQLite/PostgreSQL configuration and schema
│       ├── market_history.py # Canonical market-history preparation
│       └── market_data.py    # Yahoo Finance data download workflow
├── data/
│   └── market_data.db        # Local SQLite database
├── docs/
│   └── deployment.md         # Neon and Render deployment runbook
├── frontend/
│   ├── app.js                # API calls and dashboard behavior
│   ├── index.html            # Dashboard markup
│   ├── login.html            # Public single-user login page
│   └── style.css             # Dashboard styles
├── scripts/
│   ├── deployment_smoke.py   # Authenticated post-deployment verification
│   └── generate_auth_secrets.py # Password hash/session secret generator
├── render.yaml               # Render Blueprint
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

| Metric | Definition |
| --- | --- |
| 1-day return | Percentage change over 1 trading session, requiring the latest 2 consecutive source observations. |
| 1-week return | Percentage change over 5 trading sessions, requiring the latest 6 consecutive source observations. |
| 1-month return | Percentage change over 21 trading sessions, requiring the latest 22 consecutive source observations. |
| 3-month return | Percentage change over 63 trading sessions, requiring the latest 64 consecutive source observations. |
| 1-year return | Percentage change over 252 trading sessions, requiring the latest 253 consecutive source observations. |
| Year-to-date return | Percentage change from the final valid close before January 1 to the latest close. The anchor must be within seven calendar days of January 1, and every source observation through the latest date must have a valid close. |
| 52-week high and low | Highest stored `High` and lowest stored `Low` in the most recent 252 covered trading-session rows. |
| 52-week range position | `(latest close - 52-week low) / (52-week high - 52-week low) × 100`. A flat high/low range returns `null`. |
| Current volume vs. 20-day average | Percentage difference between the latest volume and the mean volume of the prior 20 stored trading sessions. The current session is excluded from the average. |
| SMA20, SMA50, and SMA200 | Arithmetic mean of the latest 20, 50, or 200 consecutive stored closing prices. |
| 30-day annualized volatility | Sample standard deviation of the latest 30 daily close-to-close returns, multiplied by `√252` and expressed as a percentage. This requires 31 valid consecutive closes. |
| 1-year maximum drawdown | Largest peak-to-trough decline in the most recent 252 covered trading-session rows, calculated as the minimum of `close / running peak - 1` and expressed as a percentage. |

Percentage return is calculated as `(latest close / comparison close - 1) ×
100`. Session-return windows must end at the canonical latest finite close,
contain exactly `N + 1` consecutive source observations, contain only finite
closes, and have no observation gap greater than seven calendar days. The
52-week and drawdown windows apply the same coverage rules to 252 rows. A zero
comparison close, missing or non-finite observation, incomplete rolling window,
or excessive gap returns `null` rather than a partial or placeholder metric.
Flat prices correctly produce zero return, zero volatility, and zero drawdown.

The canonical as-of row is the latest chronological row with a finite close.
`GET /latest/{symbol}`, the analytics summary, and the analytics series all end
on that row. Later rows with missing or non-finite closes are excluded from the
dashboard series. Because Yahoo Finance supplies daily observations, the
dashboard labels freshness as a date (`YYYY-MM-DD`) without implying an
intraday time or timezone.

For backward compatibility, the analytics summary still includes
`daily_return_pct`, `sma_20`, `sma_50`, and the all-history
`annualized_volatility_pct` field. The new period-return and market-context
fields are added alongside them. The analytics series endpoint now returns
close, volume, SMA20, SMA50, SMA200, and daily return values for each available
date; unavailable rolling values are `null`.

## API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | Public check that the API process is running |
| `GET`, `POST` | `/login` | Public login page and credential submission |
| `POST` | `/logout` | Ends the authenticated session |
| `GET` | `/ready` | Checks whether the configured database is reachable |
| `GET` | `/symbols` | Lists symbols currently stored in SQLite |
| `GET` | `/stocks/{symbol}` | Returns stored historical OHLCV data |
| `GET` | `/latest/{symbol}` | Returns the latest stored OHLCV record |
| `GET` | `/analytics/{symbol}` | Returns the latest computed analytics summary |
| `GET` | `/analytics/{symbol}/series` | Returns the computed analytics time series |

All routes except `/login` and `/health` require authentication, including the
dashboard, frontend files, `/ready`, `/docs`, `/redoc`, and `/openapi.json`.
Unauthenticated browser requests are redirected to the login page; API requests
receive HTTP 401. Every response sends `X-Robots-Tag: noindex, nofollow,
noarchive`, and both HTML pages contain an equivalent robots meta directive.

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
pip install -r requirements.txt
```

For local test development, install the production and Python test dependencies:

```bash
pip install -r requirements-dev.txt
```

### 3. Provision the database schema

```bash
alembic upgrade head
```

Run migrations once as a deployment or release step before starting Uvicorn.
Local development defaults to `sqlite:///data/market_data.db`. In production,
set `APP_ENV=production` and provide `DATABASE_URL` before running migrations or
starting the application. PostgreSQL connections default to a five-second
connection timeout; set `DATABASE_CONNECT_TIMEOUT` to change it, or include
`connect_timeout` directly in `DATABASE_URL`.

### 4. Configure single-user authentication

Choose `AUTH_USERNAME`, then generate a password hash and independent random
session secret. The generator reads the password without echoing it and prints
only derived/generated values:

```bash
python scripts/generate_auth_secrets.py
```

Set `AUTH_USERNAME`, the printed `AUTH_PASSWORD_HASH`, and the printed
`SESSION_SECRET` in the process environment. Do not set `AUTH_PASSWORD_HASH` to
the password itself, commit any secret, or put the plaintext password in an
environment file. The password hash uses scrypt. Sessions are signed, expire
after 12 hours, and use an HttpOnly, SameSite=Lax cookie; production cookies also
use `Secure`. Login failures are throttled in-process with no external service.

Production returns HTTP 503 for protected routes and `/login` if any required
authentication setting is absent. `/health` remains available so the platform
can distinguish a running but misconfigured service.

### 5. Download market data

From the project root, run:

```bash
python backend/app/market_data.py
```

This downloads one year of history for the symbols configured in
`TRACKED_SYMBOLS` and saves it to the provisioned database.

### 6. Start the application

```bash
uvicorn backend.app.api:app --reload
```

Open the dashboard at `http://127.0.0.1:8000` and sign in. FastAPI's interactive
API documentation is available to the authenticated user at
`http://127.0.0.1:8000/docs`.

## Deployment

The repository includes a Render Blueprint for one Python web service. Production
uses a user-supplied PostgreSQL `DATABASE_URL`; the Blueprint does not provision
SQLite storage or run migrations during application startup. See the
[Neon and Render deployment checklist](docs/deployment.md) for the required
one-time migration, secure environment setup, verification, and rollback notes.

## Tests

Run the backend and API tests with:

```bash
python -m pytest -q
```

Run the Chromium dashboard tests with:

```bash
npm ci
npx playwright install chromium
npm run test:frontend
```

## Future Roadmap

- Relative Strength Index (RSI)
- Moving Average Convergence Divergence (MACD)
- Bollinger Bands
- Portfolio tracking
- Background data updates
- C++ analytics engine integration
