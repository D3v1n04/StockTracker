import sqlite3
from unittest.mock import patch

import pytest
from sqlalchemy import inspect

from backend.app import database
from backend.app.data_access import get_stock_history


def test_default_database_url(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert database.get_database_url() == "sqlite:///data/market_data.db"

    for empty_value in ("", "   "):
        monkeypatch.setenv("DATABASE_URL", empty_value)
        assert database.get_database_url() == "sqlite:///data/market_data.db"


@pytest.mark.parametrize("database_url", [None, "", "   "])
def test_production_requires_database_url(monkeypatch, database_url):
    monkeypatch.setenv("APP_ENV", "production")
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)

    with pytest.raises(
        database.DatabaseConfigurationError,
        match="DATABASE_URL is required when APP_ENV=production",
    ):
        database.get_database_url()


def test_database_url_environment_override(monkeypatch, tmp_path):
    database_url = f"sqlite:///{tmp_path / 'override.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert database.get_database_url() == database_url


def test_postgres_urls_use_psycopg_driver():
    assert database.normalize_database_url(
        "postgres://user:password@database.example/stocks"
    ) == "postgresql+psycopg://user:password@database.example/stocks"
    assert database.normalize_database_url(
        "postgresql://user:password@database.example/stocks"
    ) == "postgresql+psycopg://user:password@database.example/stocks"

    engine = database.create_database_engine(
        "postgresql://user:password@database.example/stocks"
    )
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()


def test_postgres_timeout_preserves_url_query(monkeypatch):
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", "7")
    database_url = (
        "postgresql://user:password@database.example/stocks"
        "?sslmode=require&application_name=stocktracker"
    )

    with patch.object(database, "create_engine") as create_engine:
        database.create_database_engine(database_url)

    url = create_engine.call_args.args[0]
    options = create_engine.call_args.kwargs
    assert dict(url.query) == {
        "sslmode": "require",
        "application_name": "stocktracker",
    }
    assert options["connect_args"] == {"connect_timeout": 7}
    assert options["pool_pre_ping"] is True


def test_postgres_url_connect_timeout_takes_precedence(monkeypatch):
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", "invalid")
    database_url = (
        "postgresql://user:password@database.example/stocks"
        "?sslmode=require&connect_timeout=11"
    )

    with patch.object(database, "create_engine") as create_engine:
        database.create_database_engine(database_url)

    url = create_engine.call_args.args[0]
    options = create_engine.call_args.kwargs
    assert dict(url.query) == {
        "sslmode": "require",
        "connect_timeout": "11",
    }
    assert options["connect_args"] == {}


@pytest.mark.parametrize("timeout", ["", "0", "-1", "invalid"])
def test_invalid_postgres_connect_timeout(monkeypatch, timeout):
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", timeout)

    with pytest.raises(
        database.DatabaseConfigurationError,
        match="DATABASE_CONNECT_TIMEOUT must be a positive integer",
    ):
        database.create_database_engine(
            "postgresql://user:password@database.example/stocks"
        )


def test_sqlite_engine_creates_parent_directory(tmp_path):
    database_path = tmp_path / "nested" / "market_data.db"

    with patch.object(database, "create_engine") as create_engine:
        database.create_database_engine(f"sqlite:///{database_path}")

    assert database_path.parent.is_dir()
    options = create_engine.call_args.kwargs
    assert options["connect_args"] == {"check_same_thread": False}
    assert "pool_pre_ping" not in options


def test_schema_initialization_is_idempotent(tmp_path):
    engine = database.create_database_engine(
        f"sqlite:///{tmp_path / 'schema.db'}"
    )
    try:
        database.initialize_database(engine)
        database.initialize_database(engine)

        inspector = inspect(engine)
        assert "price_history" in inspector.get_table_names()
        assert [
            column["name"] for column in inspector.get_columns("price_history")
        ] == ["Symbol", "Date", "Open", "High", "Low", "Close", "Volume"]
        assert set(
            inspector.get_pk_constraint("price_history")["constrained_columns"]
        ) == {"Symbol", "Date"}
    finally:
        engine.dispose()


def test_existing_sqlite_schema_remains_readable(monkeypatch, tmp_path):
    database_path = tmp_path / "existing.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE price_history (
            Symbol TEXT NOT NULL,
            Date TEXT NOT NULL,
            Open REAL,
            High REAL,
            Low REAL,
            Close REAL,
            Volume INTEGER,
            PRIMARY KEY (Symbol, Date)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO price_history
        (Symbol, Date, Open, High, Low, Close, Volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("TEST", "2024-01-01", 99.0, 101.0, 98.0, 100.0, 1_000),
    )
    connection.commit()
    connection.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    database.reset_engine()
    try:
        database.initialize_database()

        assert get_stock_history("TEST") == [
            {
                "Symbol": "TEST",
                "Date": "2024-01-01",
                "Open": 99.0,
                "High": 101.0,
                "Low": 98.0,
                "Close": 100.0,
                "Volume": 1_000,
            }
        ]
    finally:
        database.reset_engine()
