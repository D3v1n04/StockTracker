import os
from pathlib import Path
from typing import Any

from sqlalchemy import BigInteger, Column, Float, MetaData, String, Table, create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import Pool


DEFAULT_DATABASE_URL = "sqlite:///data/market_data.db"
DEFAULT_POSTGRES_CONNECT_TIMEOUT = 5

metadata = MetaData()

price_history = Table(
    "price_history",
    metadata,
    Column("Symbol", String, primary_key=True),
    Column("Date", String, primary_key=True),
    Column("Open", Float),
    Column("High", Float),
    Column("Low", Float),
    Column("Close", Float),
    Column("Volume", BigInteger),
)

_engine = None
_engine_url = None


class DatabaseConfigurationError(RuntimeError):
    pass


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def get_database_url() -> str:
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    database_url = os.getenv("DATABASE_URL", "").strip()

    if app_env == "production" and not database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required when APP_ENV=production"
        )

    return normalize_database_url(database_url or DEFAULT_DATABASE_URL)


def get_postgres_connect_timeout() -> int:
    raw_timeout = os.getenv(
        "DATABASE_CONNECT_TIMEOUT",
        str(DEFAULT_POSTGRES_CONNECT_TIMEOUT),
    ).strip()

    try:
        timeout = int(raw_timeout)
    except ValueError as error:
        raise DatabaseConfigurationError(
            "DATABASE_CONNECT_TIMEOUT must be a positive integer"
        ) from error

    if timeout <= 0:
        raise DatabaseConfigurationError(
            "DATABASE_CONNECT_TIMEOUT must be a positive integer"
        )

    return timeout


def create_database_engine(
    database_url: str | None = None,
    poolclass: type[Pool] | None = None,
) -> Engine:
    resolved_url = normalize_database_url(database_url or get_database_url())
    url = make_url(resolved_url)
    connect_args: dict[str, Any] = {}
    engine_options: dict[str, Any] = {}

    if url.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    elif url.get_backend_name() == "postgresql":
        if "connect_timeout" not in url.query:
            connect_args["connect_timeout"] = get_postgres_connect_timeout()
        engine_options["pool_pre_ping"] = True

    if poolclass is not None:
        engine_options["poolclass"] = poolclass

    return create_engine(
        url,
        connect_args=connect_args,
        **engine_options,
    )


def get_engine() -> Engine:
    global _engine, _engine_url

    database_url = get_database_url()
    if _engine is None or _engine_url != database_url:
        if _engine is not None:
            _engine.dispose()
        _engine = create_database_engine(database_url)
        _engine_url = database_url

    return _engine


def reset_engine() -> None:
    global _engine, _engine_url

    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None


def initialize_database(engine: Engine | None = None) -> None:
    metadata.create_all(bind=engine or get_engine())


def check_database_connection() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
