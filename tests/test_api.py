from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app import database
from backend.app import api as api_module
from backend.app.api import app
from backend.app.data_access import save_stock_history


TEST_SYMBOL = "TEST"


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "market_data.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    database.reset_engine()
    database.initialize_database()

    start_date = date(2024, 1, 1)
    rows = []
    for index in range(60):
        close = 100.0 + index
        rows.append(
            {
                "Date": str(start_date + timedelta(days=index)),
                "Open": close - 1.0,
                "High": close + 1.0,
                "Low": close - 2.0,
                "Close": close,
                "Volume": 1_000 + index,
            }
        )

    history = pd.DataFrame(rows)
    save_stock_history(history, TEST_SYMBOL)
    save_stock_history(history, TEST_SYMBOL)

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        database.reset_engine()


def test_root_serves_dashboard(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "StockTracker Dashboard" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_require_database(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database.reset_engine()

    with TestClient(app) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_does_not_create_database_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "not-created.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    database.reset_engine()

    with TestClient(app) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert not database_path.exists()


def test_ready(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_when_database_is_unavailable(client, monkeypatch):
    def unavailable():
        raise OperationalError("SELECT 1", {}, Exception("unavailable"))

    monkeypatch.setattr(api_module, "check_database_connection", unavailable)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_ready_when_production_database_url_is_missing(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database.reset_engine()

    with TestClient(app) as test_client:
        response = test_client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_symbols(client):
    response = client.get("/symbols")

    assert response.status_code == 200
    assert response.json() == {"symbols": [TEST_SYMBOL]}


def test_stock_history(client):
    response = client.get(f"/stocks/{TEST_SYMBOL.lower()}")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == TEST_SYMBOL
    assert body["count"] == 60
    assert body["data"][0]["Close"] == 100.0
    assert body["data"][-1]["Close"] == 159.0


def test_latest_stock_information(client):
    response = client.get(f"/latest/{TEST_SYMBOL.lower()}")

    assert response.status_code == 200
    assert response.json() == {
        "Symbol": TEST_SYMBOL,
        "Date": "2024-02-29",
        "Open": 158.0,
        "High": 160.0,
        "Low": 157.0,
        "Close": 159.0,
        "Volume": 1_059,
    }


def test_analytics_summary(client):
    response = client.get(f"/analytics/{TEST_SYMBOL.lower()}")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == TEST_SYMBOL
    assert body["date"] == "2024-02-29"
    assert body["latest_close"] == 159.0
    assert body["sma_20"] == pytest.approx(149.5)
    assert body["sma_50"] == pytest.approx(134.5)
    assert body["daily_return_pct"] == pytest.approx((159.0 - 158.0) / 158.0 * 100)
    assert body["annualized_volatility_pct"] > 0
    assert body["data_points"] == 60


def test_analytics_series(client):
    response = client.get(f"/analytics/{TEST_SYMBOL.lower()}/series")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == TEST_SYMBOL
    assert body["count"] == 60
    assert body["data"][0] == {
        "Date": "2024-01-01",
        "Close": 100.0,
        "SMA20": None,
        "SMA50": None,
        "DailyReturnPct": None,
    }
    assert body["data"][-1]["SMA20"] == pytest.approx(149.5)
    assert body["data"][-1]["SMA50"] == pytest.approx(134.5)


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/stocks/MISSING", 404),
        ("/latest/MISSING", 404),
        ("/analytics/MISSING", 200),
        ("/analytics/MISSING/series", 200),
    ],
)
def test_missing_symbol(client, path, expected_status):
    response = client.get(path)

    assert response.status_code == expected_status
    if expected_status == 404:
        assert response.json() == {"detail": "No data found for MISSING"}
    else:
        assert response.json() == {"error": "No data found for MISSING"}
