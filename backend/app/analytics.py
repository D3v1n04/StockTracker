import pandas as pd
from backend.app.data_access import get_stock_history

def get_stock_metrics(symbol: str):
    symbol = symbol.upper()
    
    history = get_stock_history(symbol)
    
    if not history:
        return None
    
    df = pd.DataFrame(history)
    
    df['Date'] = pd.to_datetime(df['Date'])
    df['Close'] = pd.to_numeric(df['Close'])
    
    df = df.sort_values("Date")
    
    latest_row = df.iloc[-1]
    previous_row = df.iloc[-2] if len(df) > 1 else None
    
    latest_close = latest_row['Close']
    
    sma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    sma50 = df['Close'].rolling(window=50).mean().iloc[-1]
    
    if previous_row is not None:
        previous_close = previous_row['Close']
        daily_return_pct = ((latest_close - previous_close) / previous_close) * 100
    else:
        daily_return_pct = None
    
    daily_returns = df['Close'].pct_change()
    volatility = daily_returns.std() * (252 ** 0.5) * 100
    
    return{
        "symbol": symbol,
        "date": str(latest_row["Date"].date()),
        "latest_close": latest_close,
        "sma_20": None if pd.isna(sma20) else float(sma20),
        "sma_50": None if pd.isna(sma50) else float(sma50),
        "daily_return_pct": None if daily_return_pct is None else float(daily_return_pct),
        "annualized_volatility_pct": None if pd.isna(volatility) else float(volatility),
        "data_points": len(df),
    }
    
def get_stock_analytics_series(symbol: str):
    symbol = symbol.upper()
    
    history = get_stock_history(symbol)
    
    if not history:
        return None
    
    df = pd.DataFrame(history)
    
    df['Date'] = pd.to_datetime(df['Date'])
    df['Close'] = pd.to_numeric(df['Close'])
    
    df = df.sort_values("Date")
    
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA50'] = df['Close'].rolling(window=50).mean()
    df['DailyReturnPct'] = df['Close'].pct_change() * 100
    
    result = []
    
    for _, row in df.iterrows():
        result.append({
            "Date": str(row["Date"].date()),
            "Close": float(row["Close"]),
            "SMA20": None if pd.isna(row["SMA20"]) else float(row["SMA20"]),
            "SMA50": None if pd.isna(row["SMA50"]) else float(row["SMA50"]),
            "DailyReturnPct": None if pd.isna(row["DailyReturnPct"]) else float(row["DailyReturnPct"]),
        })
        
    return {
        "symbol": symbol,
        "count": len(result),
        "data": result,
    }    
