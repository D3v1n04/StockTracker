import sqlite3
import pandas as pd

DB_PATH = "data/market_data.db"

# Database access functions
def get_connection():
    return sqlite3.connect(DB_PATH)

# Initialize the database and create the price_history table if it doesn't exist
def initialize_database(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            Symbol TEXT NOT NULL,
            Date TEXT NOT NULL,
            Open REAL,
            High REAL,
            Low REAL,
            Close REAL,
            Volume INTEGER,
            PRIMARY KEY (Symbol, Date)
        )
    """)
    conn.commit()

# Save stock history to the database
def save_stock_history(conn, data: pd.DataFrame, symbol: str):
    for _, row in data.iterrows():
        conn.execute("""
            INSERT OR IGNORE INTO price_history
            (Symbol, Date, Open, High, Low, Close, Volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            str(row["Date"]),
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
            int(row["Volume"]),
        ))

    conn.commit()
    print(f"Saved data for {symbol}")

# Retrieve stock history from the database
def get_stock_history(symbol: str):
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT Symbol, Date, Open, High, Low, Close, Volume
        FROM price_history
        WHERE Symbol = ?
        ORDER BY Date ASC
    """, (symbol,)).fetchall()

    conn.close()

    return [dict(row) for row in rows]

def get_all_symbols():
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT DISTINCT Symbol
        FROM price_history
        ORDER BY Symbol ASC
    """).fetchall()

    conn.close()

    return [row["Symbol"] for row in rows]


def get_latest_price(symbol: str):
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    row = conn.execute("""
        SELECT Symbol, Date, Open, High, Low, Close, Volume
        FROM price_history
        WHERE Symbol = ?
        ORDER BY Date DESC
        LIMIT 1
    """, (symbol,)).fetchone()

    conn.close()

    if row is None:
        return None

    return dict(row)

if __name__ == "__main__":
    data = get_stock_history("MSFT")
    print(len(data))
    print(data[:5])