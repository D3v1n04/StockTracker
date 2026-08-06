import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app import database
from backend.app import api as api_module
from backend.app.auth import (
    SESSION_MAX_AGE,
    create_session,
    hash_password,
    load_auth_config,
    login_throttle,
    valid_session,
    verify_password,
)
from backend.app.api import app
from backend.app.data_access import save_stock_history
from scripts import generate_auth_secrets


TEST_SYMBOL = "TEST"
TEST_USERNAME = "test-user"
TEST_PASSWORD = "test-password"
TEST_SESSION_SECRET = "test-session-secret-that-is-at-least-32-bytes"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD, salt=b"0123456789abcdef")


def configure_auth(monkeypatch, *, username=TEST_USERNAME, production=False):
    monkeypatch.setenv("AUTH_USERNAME", username)
    monkeypatch.setenv("AUTH_PASSWORD_HASH", TEST_PASSWORD_HASH)
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    if production:
        monkeypatch.setenv("APP_ENV", "production")
    else:
        monkeypatch.delenv("APP_ENV", raising=False)
    login_throttle.reset()


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "market_data.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    configure_auth(monkeypatch)
    database.reset_engine()
    database.initialize_database()

    rows = []
    for index, observation_date in enumerate(
        pd.bdate_range("2024-01-02", periods=60)
    ):
        close = 100.0 + index
        rows.append(
            {
                "Date": str(observation_date.date()),
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
            login = test_client.post(
                "/login",
                data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
                follow_redirects=False,
            )
            assert login.status_code == 303
            yield test_client
    finally:
        database.reset_engine()


def test_unauthenticated_pages_redirect_and_apis_return_401(monkeypatch):
    configure_auth(monkeypatch)
    with TestClient(app) as test_client:
        for path in ("/", "/index.html", "/app.js", "/style.css", "/docs", "/redoc"):
            response = test_client.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/login"

        for path in ("/symbols", "/stocks/TEST", "/latest/TEST", "/analytics/TEST", "/analytics/TEST/series", "/ready", "/openapi.json"):
            response = test_client.get(path)
            assert response.status_code == 401
            assert response.json() == {"detail": "Authentication required"}
            assert response.headers["www-authenticate"] == "Session"


def test_login_success_sets_signed_cookie_and_allows_dashboard(monkeypatch):
    configure_auth(monkeypatch)
    with TestClient(app) as test_client:
        login_page = test_client.get("/login")
        assert login_page.status_code == 200
        assert 'name="robots" content="noindex, nofollow, noarchive"' in login_page.text

        response = test_client.post(
            "/login",
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        cookie = response.headers["set-cookie"]
        assert "stocktracker_session=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Max-Age=43200" in cookie
        assert "Secure" not in cookie
        assert TEST_PASSWORD not in cookie
        assert test_client.get("/").status_code == 200


def test_production_session_cookie_is_secure(monkeypatch):
    configure_auth(monkeypatch, production=True)
    with TestClient(app, base_url="https://testserver") as test_client:
        response = test_client.post(
            "/login",
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]


def test_incorrect_credentials_do_not_create_session(monkeypatch):
    configure_auth(monkeypatch)
    with TestClient(app) as test_client:
        response = test_client.post(
            "/login",
            data={"username": TEST_USERNAME, "password": "incorrect"},
            follow_redirects=False,
        )
        assert response.status_code == 401
        assert "Invalid username or password." in response.text
        assert "set-cookie" not in response.headers
        assert TEST_PASSWORD not in response.text
        assert test_client.get("/symbols").status_code == 401


def test_logout_clears_session_and_reprotects_dashboard(monkeypatch):
    configure_auth(monkeypatch)
    with TestClient(app) as test_client:
        test_client.post(
            "/login", data={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )
        response = test_client.post("/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        assert "stocktracker_session=" in response.headers["set-cookie"]
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert test_client.get("/", follow_redirects=False).status_code == 303


def test_login_is_throttled_after_repeated_failures(monkeypatch):
    configure_auth(monkeypatch)
    with TestClient(app) as test_client:
        for _ in range(5):
            response = test_client.post(
                "/login",
                data={"username": TEST_USERNAME, "password": "incorrect"},
            )
            assert response.status_code == 401
        response = test_client.post(
            "/login",
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) >= 1
        assert "Too many attempts" in response.text


@pytest.mark.parametrize(
    "cookie",
    ["not-a-session", ".", "%%%.$$$", "eyJleHAiOiJub3QtaW50In0.invalid", "x" * 3000],
)
def test_malformed_sessions_are_rejected_safely(monkeypatch, cookie):
    configure_auth(monkeypatch)
    with TestClient(app) as test_client:
        test_client.cookies.set("stocktracker_session", cookie)
        response = test_client.get("/symbols")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_sessions_reject_tampering_expiration_and_changed_username(monkeypatch):
    configure_auth(monkeypatch)
    config = load_auth_config()
    session = create_session(config, now=1_000)
    assert valid_session(session, config, now=999 + SESSION_MAX_AGE)
    assert not valid_session(session + "x", config, now=1_001)
    assert not valid_session(session, config, now=1_000 + SESSION_MAX_AGE)

    configure_auth(monkeypatch, username="another-user")
    assert not valid_session(session, load_auth_config(), now=1_001)


def test_non_ascii_username_and_hostile_login_input_are_handled(monkeypatch):
    configure_auth(monkeypatch, username="álïçé用户")
    with TestClient(app) as test_client:
        response = test_client.post(
            "/login",
            data={"username": "álïçé用户", "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303

    configure_auth(monkeypatch)
    with TestClient(app) as test_client:
        malformed = test_client.post(
            "/login",
            content=b"username=%FF&password=value&password=duplicate",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        oversized = test_client.post(
            "/login",
            content=b"username=x&password=" + b"x" * 17_000,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        wrong_content_type = test_client.post(
            "/login",
            content=b"username=test-user&password=test-password",
            headers={"content-type": "text/plain"},
        )
    assert malformed.status_code == 401
    assert oversized.status_code == 401
    assert wrong_content_type.status_code == 401


def test_secret_generator_outputs_only_hash_and_random_session_secret(monkeypatch, capsys):
    answers = iter([TEST_PASSWORD, TEST_PASSWORD])
    monkeypatch.setattr(generate_auth_secrets.getpass, "getpass", lambda _prompt: next(answers))

    assert generate_auth_secrets.main() == 0
    output = capsys.readouterr().out
    assert TEST_PASSWORD not in output
    values = dict(line.split("=", 1) for line in output.strip().splitlines())
    assert verify_password(TEST_PASSWORD, values["AUTH_PASSWORD_HASH"])
    assert len(values["SESSION_SECRET"]) >= 48


@pytest.mark.parametrize("missing_name", ["AUTH_USERNAME", "AUTH_PASSWORD_HASH", "SESSION_SECRET"])
def test_missing_production_auth_secret_fails_closed_but_health_is_public(
    monkeypatch, missing_name
):
    configure_auth(monkeypatch, production=True)
    monkeypatch.delenv(missing_name, raising=False)
    with TestClient(app) as test_client:
        health = test_client.get("/health")
        login = test_client.get("/login")
        api = test_client.get("/symbols")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert login.status_code == 503
    assert api.status_code == 503
    assert login.json() == {"detail": "Authentication service unavailable"}
    assert api.json() == {"detail": "Authentication service unavailable"}


def test_root_serves_dashboard(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "StockTracker Dashboard" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_dashboard_includes_market_context_controls_and_responsive_assets(client):
    dashboard = client.get("/")
    script = client.get("/app.js")
    stylesheet = client.get("/style.css")

    assert dashboard.status_code == 200
    assert 'id="contextSummary"' in dashboard.text
    assert 'data-range="1M"' in dashboard.text
    assert 'data-range="MAX"' in dashboard.text
    assert 'data-sma="SMA200"' in dashboard.text
    assert 'id="volumeChart"' in dashboard.text
    assert 'action="/logout"' in dashboard.text
    assert 'name="robots" content="noindex, nofollow, noarchive"' in dashboard.text

    assert script.status_code == 200
    assert "fetchJson(`/analytics/${symbol}`)" in script.text
    assert "fetchJson(`/analytics/${symbol}/series`)" in script.text
    assert "http://localhost:8000" not in script.text

    assert stylesheet.status_code == 200
    assert "@media (max-width: 700px)" in stylesheet.text
    assert "@media (max-width: 430px)" in stylesheet.text


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
    monkeypatch.setenv("AUTH_USERNAME", TEST_USERNAME)
    monkeypatch.setenv("AUTH_PASSWORD_HASH", TEST_PASSWORD_HASH)
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    database.reset_engine()

    with TestClient(app) as test_client:
        test_client.cookies.set(
            "stocktracker_session",
            create_session(load_auth_config()),
        )
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
        "Date": "2024-03-25",
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
    assert body["date"] == "2024-03-25"
    assert body["as_of_date"] == "2024-03-25"
    assert body["latest_data_date"] == "2024-03-25"
    assert body["latest_data_timestamp"] == "2024-03-25 00:00:00"
    assert body["latest_close"] == 159.0
    assert body["sma_20"] == pytest.approx(149.5)
    assert body["sma_50"] == pytest.approx(134.5)
    assert body["sma_200"] is None
    assert body["daily_return_pct"] == pytest.approx((159.0 - 158.0) / 158.0 * 100)
    assert body["return_1d_pct"] == body["daily_return_pct"]
    assert body["return_1w_pct"] == pytest.approx((159.0 / 154.0 - 1) * 100)
    assert body["return_1m_pct"] == pytest.approx((159.0 / 138.0 - 1) * 100)
    assert body["return_3m_pct"] is None
    assert body["return_ytd_pct"] is None
    assert body["return_1y_pct"] is None
    assert body["high_52w"] is None
    assert body["low_52w"] is None
    assert body["range_position_52w_pct"] is None
    assert body["current_volume"] == 1_059
    assert body["average_volume_20d"] == pytest.approx(1_048.5)
    assert body["volume_vs_average_20d_pct"] == pytest.approx(
        (1_059 / 1_048.5 - 1) * 100
    )
    assert body["annualized_volatility_30d_pct"] > 0
    assert body["max_drawdown_1y_pct"] is None
    assert body["annualized_volatility_pct"] > 0
    assert body["data_points"] == 60


def test_analytics_series(client):
    response = client.get(f"/analytics/{TEST_SYMBOL.lower()}/series")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == TEST_SYMBOL
    assert body["count"] == 60
    assert body["data"][0] == {
        "Date": "2024-01-02",
        "Close": 100.0,
        "Volume": 1_000.0,
        "SMA20": None,
        "SMA50": None,
        "SMA200": None,
        "DailyReturnPct": None,
    }
    assert body["data"][-1]["SMA20"] == pytest.approx(149.5)
    assert body["data"][-1]["SMA50"] == pytest.approx(134.5)
    assert body["data"][-1]["SMA200"] is None


def test_endpoints_use_same_canonical_latest_finite_close(client):
    with database.get_engine().begin() as connection:
        connection.execute(
            database.price_history.insert(),
            [
                {
                    "Symbol": TEST_SYMBOL,
                    "Date": "2024-03-26",
                    "Open": 160.0,
                    "High": 161.0,
                    "Low": 159.0,
                    "Close": None,
                    "Volume": 2_000,
                },
                {
                    "Symbol": TEST_SYMBOL,
                    "Date": "2024-03-27",
                    "Open": float("nan"),
                    "High": float("inf"),
                    "Low": float("-inf"),
                    "Close": float("inf"),
                    "Volume": 2_001,
                },
            ],
        )

    latest = client.get(f"/latest/{TEST_SYMBOL}")
    summary = client.get(f"/analytics/{TEST_SYMBOL}")
    series = client.get(f"/analytics/{TEST_SYMBOL}/series")
    raw = client.get(f"/stocks/{TEST_SYMBOL}")

    assert latest.status_code == 200
    assert latest.json()["Date"] == "2024-03-25"
    assert latest.json()["Close"] == 159.0
    assert summary.json()["date"] == "2024-03-25"
    assert summary.json()["as_of_date"] == "2024-03-25"
    assert summary.json()["latest_close"] == 159.0
    assert series.json()["as_of_date"] == "2024-03-25"
    assert series.json()["data"][-1]["Date"] == "2024-03-25"
    assert series.json()["count"] == 60

    for response in (latest, summary, series, raw):
        json.dumps(response.json(), allow_nan=False)
    assert raw.json()["data"][-1]["Close"] is None
    assert raw.json()["data"][-1]["Open"] is None
    assert raw.json()["data"][-1]["High"] is None
    assert raw.json()["data"][-1]["Low"] is None


def test_nonfinite_latest_ohlcv_is_json_safe(client):
    symbol = "SAFE"
    with database.get_engine().begin() as connection:
        connection.execute(
            database.price_history.insert(),
            {
                "Symbol": symbol,
                "Date": "2024-01-02",
                "Open": float("nan"),
                "High": float("inf"),
                "Low": float("-inf"),
                "Close": 100.0,
                "Volume": float("inf"),
            },
        )

    responses = [
        client.get(f"/stocks/{symbol}"),
        client.get(f"/latest/{symbol}"),
        client.get(f"/analytics/{symbol}"),
        client.get(f"/analytics/{symbol}/series"),
    ]
    for response in responses:
        assert response.status_code == 200
        json.dumps(response.json(), allow_nan=False)

    latest = responses[1].json()
    assert latest["Close"] == 100.0
    assert latest["Open"] is None
    assert latest["High"] is None
    assert latest["Low"] is None
    assert latest["Volume"] is None


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
