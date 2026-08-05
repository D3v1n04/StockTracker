import math

import pandas as pd

from backend.app.data_access import get_stock_history
from backend.app.market_history import finite_number, prepare_canonical_history


TRADING_DAYS_PER_YEAR = 252
MAX_OBSERVATION_GAP_DAYS = 7
RETURN_SESSIONS = {
    "return_1d_pct": 1,
    "return_1w_pct": 5,
    "return_1m_pct": 21,
    "return_3m_pct": 63,
    "return_1y_pct": 252,
}


def _has_covered_observations(window, columns, expected_rows):
    if len(window) != expected_rows:
        return False
    if not window[list(columns)].notna().all().all():
        return False

    gaps = window["Date"].diff().dropna().dt.days
    return gaps.le(MAX_OBSERVATION_GAP_DAYS).all()


def _percentage_return(latest_close, anchor_close):
    latest = finite_number(latest_close)
    anchor = finite_number(anchor_close)
    if latest is None or anchor in (None, 0):
        return None
    return finite_number((latest / anchor - 1) * 100)


def _session_return(df, sessions):
    window = df.tail(sessions + 1)
    if not _has_covered_observations(window, ("Close",), sessions + 1):
        return None
    return _percentage_return(window["Close"].iloc[-1], window["Close"].iloc[0])


def _ytd_return(df):
    latest_date = df["Date"].iloc[-1]
    year_start = pd.Timestamp(year=latest_date.year, month=1, day=1)
    anchors = df[(df["Date"] < year_start) & df["Close"].notna()]
    if anchors.empty:
        return None

    anchor = anchors.iloc[-1]
    if (year_start - anchor["Date"]).days > MAX_OBSERVATION_GAP_DAYS:
        return None

    coverage = df.loc[anchor.name :]
    if not _has_covered_observations(
        coverage,
        ("Close",),
        len(coverage),
    ):
        return None
    return _percentage_return(df["Close"].iloc[-1], anchor["Close"])


def _rolling_value(series, window):
    rolling_mean = series.rolling(window=window, min_periods=window).mean()
    return finite_number(rolling_mean.iloc[-1])


def _annualized_volatility(window):
    if not _has_covered_observations(window, ("Close",), len(window)):
        return None
    returns = window["Close"].pct_change(fill_method=None).dropna()
    if len(returns) != len(window) - 1:
        return None
    if not returns.map(math.isfinite).all():
        return None
    return finite_number(
        returns.std() * math.sqrt(TRADING_DAYS_PER_YEAR) * 100
    )


def _maximum_drawdown(window):
    if not _has_covered_observations(window, ("Close",), TRADING_DAYS_PER_YEAR):
        return None
    running_peak = window["Close"].cummax()
    if running_peak.eq(0).any():
        return None
    drawdowns = window["Close"] / running_peak - 1
    return finite_number(drawdowns.min() * 100)


def get_stock_metrics(symbol: str):
    symbol = symbol.upper()
    df = prepare_canonical_history(get_stock_history(symbol))
    if df.empty:
        return None

    latest_row = df.iloc[-1]
    latest_date = latest_row["Date"]
    latest_close = finite_number(latest_row["Close"])
    returns = {
        key: _session_return(df, sessions)
        for key, sessions in RETURN_SESSIONS.items()
    }
    returns["return_ytd_pct"] = _ytd_return(df)

    sma20 = _rolling_value(df["Close"], 20)
    sma50 = _rolling_value(df["Close"], 50)
    sma200 = _rolling_value(df["Close"], 200)

    all_returns = df["Close"].pct_change(fill_method=None).dropna()
    historical_volatility = None
    if len(all_returns) >= 2 and all_returns.map(math.isfinite).all():
        historical_volatility = finite_number(
            all_returns.std() * math.sqrt(TRADING_DAYS_PER_YEAR) * 100
        )

    recent_volatility_window = df.tail(31)
    volatility_30d = None
    if len(recent_volatility_window) == 31:
        volatility_30d = _annualized_volatility(recent_volatility_window)

    year_window = df.tail(TRADING_DAYS_PER_YEAR)
    year_is_covered = _has_covered_observations(
        year_window,
        ("Close",),
        TRADING_DAYS_PER_YEAR,
    )
    high_52w = None
    low_52w = None
    range_position_52w = None
    max_drawdown_1y = None
    if year_is_covered:
        if year_window[["High", "Low"]].notna().all().all():
            high_52w = finite_number(year_window["High"].max())
            low_52w = finite_number(year_window["Low"].min())
            if (
                high_52w is not None
                and low_52w is not None
                and high_52w != low_52w
            ):
                range_position_52w = finite_number(
                    (latest_close - low_52w) / (high_52w - low_52w) * 100
                )
        max_drawdown_1y = _maximum_drawdown(year_window)

    current_volume = finite_number(latest_row["Volume"])
    volume_window = df.tail(21)
    average_volume_20d = None
    volume_vs_average_20d = None
    if _has_covered_observations(volume_window, ("Volume",), 21):
        prior_volumes = volume_window["Volume"].iloc[:-1]
        average_volume_20d = finite_number(prior_volumes.mean())
        if current_volume is not None and average_volume_20d not in (None, 0):
            volume_vs_average_20d = finite_number(
                (current_volume / average_volume_20d - 1) * 100
            )

    as_of_date = str(latest_date.date())
    return {
        "symbol": symbol,
        "date": as_of_date,
        "as_of_date": as_of_date,
        "latest_data_date": as_of_date,
        "latest_data_timestamp": latest_date.isoformat(sep=" "),
        "latest_close": latest_close,
        "sma_20": sma20,
        "sma_50": sma50,
        "sma_200": sma200,
        "daily_return_pct": returns["return_1d_pct"],
        "annualized_volatility_pct": historical_volatility,
        "annualized_volatility_30d_pct": volatility_30d,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "range_position_52w_pct": range_position_52w,
        "current_volume": current_volume,
        "average_volume_20d": average_volume_20d,
        "volume_vs_average_20d_pct": volume_vs_average_20d,
        "max_drawdown_1y_pct": max_drawdown_1y,
        "data_points": finite_number(len(df)),
        **returns,
    }


def get_stock_analytics_series(symbol: str):
    symbol = symbol.upper()
    df = prepare_canonical_history(get_stock_history(symbol))
    if df.empty:
        return None

    df["SMA20"] = df["Close"].rolling(window=20, min_periods=20).mean()
    df["SMA50"] = df["Close"].rolling(window=50, min_periods=50).mean()
    df["SMA200"] = df["Close"].rolling(window=200, min_periods=200).mean()
    df["DailyReturnPct"] = df["Close"].pct_change(fill_method=None) * 100

    result = []
    for _, row in df.iterrows():
        result.append(
            {
                "Date": str(row["Date"].date()),
                "Close": finite_number(row["Close"]),
                "Volume": finite_number(row["Volume"]),
                "SMA20": finite_number(row["SMA20"]),
                "SMA50": finite_number(row["SMA50"]),
                "SMA200": finite_number(row["SMA200"]),
                "DailyReturnPct": finite_number(row["DailyReturnPct"]),
            }
        )

    as_of_date = str(df["Date"].iloc[-1].date())
    return {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "count": finite_number(len(result)),
        "data": result,
    }
