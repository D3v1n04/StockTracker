from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.analytics import get_stock_metrics, get_stock_analytics_series

from backend.app.data_access import (
    get_all_symbols,
    get_latest_price,
    get_stock_history,
)


app = FastAPI(title="StockTracker API")

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
