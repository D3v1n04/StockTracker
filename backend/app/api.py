from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from backend.app.analytics import get_stock_metrics, get_stock_analytics_series
from backend.app.database import (
    DatabaseConfigurationError,
    check_database_connection,
    reset_engine,
)

from backend.app.data_access import (
    get_all_symbols,
    get_latest_price,
    get_stock_history,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        reset_engine()


app = FastAPI(title="StockTracker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/ready")
def readiness_check():
    try:
        check_database_connection()
    except DatabaseConfigurationError as error:
        logger.error("Database configuration error: %s", error)
        raise HTTPException(status_code=503, detail="Database unavailable")
    except (OSError, SQLAlchemyError):
        logger.warning("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")

    return {"status": "ready"}


@app.get("/symbols")
def read_symbols():
    return {"symbols": get_all_symbols()}


@app.get("/stocks/{symbol}")
def read_stock_history(symbol: str):
    symbol = symbol.upper()
    data = get_stock_history(symbol)

    if not data:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

    return {
        "symbol": symbol,
        "count": len(data),
        "data": data,
    }


@app.get("/latest/{symbol}")
def read_latest_price(symbol: str):
    symbol = symbol.upper()
    latest = get_latest_price(symbol)

    if latest is None:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

    return latest

@app.get("/analytics/{symbol}")
def read_stock_metrics(symbol: str):
    symbol = symbol.upper()

    metrics = get_stock_metrics(symbol)

    if metrics is None:
        return {
            "error": f"No data found for {symbol}"
        }

    return metrics

@app.get("/analytics/{symbol}/series")
def read_stock_analytics_series(symbol: str):
    symbol = symbol.upper()

    series = get_stock_analytics_series(symbol)

    if series is None:
        return {
            "error": f"No data found for {symbol}"
        }

    return series


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
