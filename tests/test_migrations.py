import sqlite3

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from backend.app import database


def run_migrations(database_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    database.reset_engine()
    command.upgrade(Config("alembic.ini"), "head")


def test_initial_migration_creates_current_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "migrated.db"
    run_migrations(database_path, monkeypatch)

    engine = database.create_database_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        assert "price_history" in inspector.get_table_names()
        assert [
            column["name"] for column in inspector.get_columns("price_history")
        ] == ["Symbol", "Date", "Open", "High", "Low", "Close", "Volume"]
        assert set(
            inspector.get_pk_constraint("price_history")["constrained_columns"]
        ) == {"Symbol", "Date"}

        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == "0001"
    finally:
        engine.dispose()
        database.reset_engine()


def test_initial_migration_adopts_compatible_existing_schema(
    tmp_path,
    monkeypatch,
):
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

    run_migrations(database_path, monkeypatch)

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT Symbol, Date, Close FROM price_history"
        ).fetchall() == [("TEST", "2024-01-01", 100.0)]
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("0001",)
    finally:
        connection.close()
        database.reset_engine()
