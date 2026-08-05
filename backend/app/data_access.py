import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

if __package__:
    from backend.app.database import get_engine, price_history
else:
    from database import get_engine, price_history


def save_stock_history(data: pd.DataFrame, symbol: str):
    records = [
        {
            "Symbol": symbol,
            "Date": str(row["Date"]),
            "Open": float(row["Open"]),
            "High": float(row["High"]),
            "Low": float(row["Low"]),
            "Close": float(row["Close"]),
            "Volume": int(row["Volume"]),
        }
        for _, row in data.iterrows()
    ]

    if not records:
        return

    engine = get_engine()
    if engine.dialect.name == "postgresql":
        statement = postgresql_insert(price_history).values(records)
        statement = statement.on_conflict_do_nothing(
            index_elements=["Symbol", "Date"]
        )
    elif engine.dialect.name == "sqlite":
        statement = sqlite_insert(price_history).values(records)
        statement = statement.on_conflict_do_nothing(
            index_elements=["Symbol", "Date"]
        )
    else:
        statement = price_history.insert().values(records)

    with engine.begin() as connection:
        connection.execute(statement)

    print(f"Saved data for {symbol}")


def get_stock_history(symbol: str):
    statement = (
        select(price_history)
        .where(price_history.c.Symbol == symbol)
        .order_by(price_history.c.Date.asc())
    )
    with get_engine().connect() as connection:
        rows = connection.execute(statement).mappings().all()

    return [dict(row) for row in rows]


def get_all_symbols():
    statement = select(price_history.c.Symbol).distinct().order_by(
        price_history.c.Symbol.asc()
    )
    with get_engine().connect() as connection:
        symbols = connection.execute(statement).scalars().all()

    return list(symbols)


def get_latest_price(symbol: str):
    statement = (
        select(price_history)
        .where(price_history.c.Symbol == symbol)
        .order_by(price_history.c.Date.desc())
        .limit(1)
    )
    with get_engine().connect() as connection:
        row = connection.execute(statement).mappings().first()

    if row is None:
        return None

    return dict(row)

if __name__ == "__main__":
    data = get_stock_history("MSFT")
    print(len(data))
    print(data[:5])
