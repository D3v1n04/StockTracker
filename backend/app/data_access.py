import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

if __package__:
    from backend.app.database import get_engine, price_history
    from backend.app.market_history import (
        canonical_latest_record,
        finite_number,
        sanitize_history_record,
    )
else:
    from database import get_engine, price_history
    from market_history import (
        canonical_latest_record,
        finite_number,
        sanitize_history_record,
    )


def save_stock_history(data: pd.DataFrame, symbol: str):
    records = []
    for _, row in data.iterrows():
        volume = finite_number(row["Volume"])
        records.append(
            {
                "Symbol": symbol,
                "Date": str(row["Date"]),
                "Open": finite_number(row["Open"]),
                "High": finite_number(row["High"]),
                "Low": finite_number(row["Low"]),
                "Close": finite_number(row["Close"]),
                "Volume": None if volume is None else int(volume),
            }
        )

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

    return [sanitize_history_record(dict(row)) for row in rows]


def get_all_symbols():
    statement = select(price_history.c.Symbol).distinct().order_by(
        price_history.c.Symbol.asc()
    )
    with get_engine().connect() as connection:
        symbols = connection.execute(statement).scalars().all()

    return list(symbols)


def get_latest_price(symbol: str):
    return canonical_latest_record(get_stock_history(symbol))


if __name__ == "__main__":
    data = get_stock_history("MSFT")
    print(len(data))
    print(data[:5])
