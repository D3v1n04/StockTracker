import yfinance as yf
import sqlite3

# Imported functions from data_access.py
from data_access import get_connection, initialize_database, save_stock_history

TRACKED_SYMBOLS = ["VIG", "SPOT", "SONY", "MSFT", "MCD", "VOO", "TSLA", "NVDA", "F"]

def fetch_stock_data(symbol: str, period: str = "1y"):
    # Fetch stock data from Yahoo Finance
    data = yf.download(symbol, period=period)

    # Drop the first level of the column index if it exists
    if hasattr(data.columns, "droplevel"):
        data.columns = data.columns.droplevel(1)

    # Reset the index to have a flat DataFrame
    data = data.reset_index()

    print(f"Downloaded {len(data)} rows for {symbol}")

    return data

def save_to_database(data, symbol: str):
    # Connect to the SQLite database
    conn = sqlite3.connect("data/market_data.db")

    print(f"Saving {len(data)} rows for {symbol}")

    data["Symbol"] = symbol

    # Save the data to the database
    data.to_sql(
        "price_history",
        conn,
        if_exists="append",
        index=False
    )

    conn.close()

if __name__ == "__main__":
    conn = get_connection()
    initialize_database(conn)

    for symbol in TRACKED_SYMBOLS:
        print(f"\nFetching {symbol}...")
        df = fetch_stock_data(symbol)
        save_stock_history(conn, df, symbol)

    conn.close()