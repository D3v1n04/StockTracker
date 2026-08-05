import yfinance as yf

if __package__:
    from backend.app.data_access import save_stock_history
else:
    from data_access import save_stock_history

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
    save_stock_history(data, symbol)

if __name__ == "__main__":
    for symbol in TRACKED_SYMBOLS:
        print(f"\nFetching {symbol}...")
        df = fetch_stock_data(symbol)
        save_stock_history(df, symbol)
