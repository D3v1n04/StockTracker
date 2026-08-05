import math
from numbers import Integral

import pandas as pd


NUMERIC_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def finite_number(value):
    """Return a JSON-safe finite number, or None for missing/non-finite input."""
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(numeric_value):
        return None
    if isinstance(value, Integral):
        return int(value)
    return numeric_value


def sanitize_history_record(record):
    sanitized = dict(record)
    for column in NUMERIC_COLUMNS:
        sanitized[column] = finite_number(sanitized.get(column))
    return sanitized


def prepare_canonical_history(history):
    """Normalize history and discard rows after the latest finite close."""
    df = pd.DataFrame(history).copy()
    if df.empty or "Date" not in df or "Close" not in df:
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for column in NUMERIC_COLUMNS:
        if column not in df:
            df[column] = float("nan")
        df[column] = pd.to_numeric(df[column], errors="coerce")
        df.loc[~df[column].map(math.isfinite), column] = float("nan")

    df = (
        df.dropna(subset=["Date"])
        .sort_values("Date")
        .drop_duplicates(subset=["Date"], keep="last")
        .reset_index(drop=True)
    )
    valid_close_rows = df[df["Close"].notna()]
    if valid_close_rows.empty:
        return pd.DataFrame()

    return df.loc[: valid_close_rows.index[-1]].copy()


def canonical_latest_record(history):
    df = prepare_canonical_history(history)
    if df.empty:
        return None

    row = df.iloc[-1]
    record = {
        "Symbol": row.get("Symbol"),
        "Date": str(row["Date"].date()),
        **{column: finite_number(row[column]) for column in NUMERIC_COLUMNS},
    }
    if record["Volume"] is not None and float(record["Volume"]).is_integer():
        record["Volume"] = int(record["Volume"])
    return record
