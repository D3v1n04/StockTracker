import json
import math

import pandas as pd
import pytest

from backend.app import analytics
from backend.app.market_history import finite_number


def make_history(
    closes,
    start="2023-01-02",
    volumes=None,
    dates=None,
    flat_range=False,
):
    if dates is None:
        dates = pd.bdate_range(start, periods=len(closes))
    if volumes is None:
        volumes = [1_000 + index for index in range(len(closes))]

    rows = []
    for date, close, volume in zip(dates, closes, volumes):
        if close is None or not math.isfinite(float(close)):
            high = close
            low = close
        elif flat_range:
            high = close
            low = close
        else:
            high = close + 2
            low = close - 2
        rows.append(
            {
                "Symbol": "TEST",
                "Date": str(date),
                "Open": close,
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": volume,
            }
        )
    return rows


def metrics_for(monkeypatch, history):
    monkeypatch.setattr(analytics, "get_stock_history", lambda _symbol: history)
    return analytics.get_stock_metrics("test")


def test_returns_use_exact_trading_session_windows(monkeypatch):
    closes = [100 + index * 0.5 for index in range(320)]
    metrics = metrics_for(monkeypatch, make_history(closes))

    expected_sessions = {
        "return_1d_pct": 1,
        "return_1w_pct": 5,
        "return_1m_pct": 21,
        "return_3m_pct": 63,
        "return_1y_pct": 252,
    }
    for key, sessions in expected_sessions.items():
        assert metrics[key] == pytest.approx(
            (closes[-1] / closes[-sessions - 1] - 1) * 100
        )
    assert metrics["daily_return_pct"] == metrics["return_1d_pct"]


def test_session_returns_reject_sparse_missing_and_nonfinite_windows(monkeypatch):
    sparse = make_history(
        [50.0, 100.0],
        dates=[pd.Timestamp("2020-01-02"), pd.Timestamp("2025-01-10")],
    )
    metrics = metrics_for(monkeypatch, sparse)
    for key in analytics.RETURN_SESSIONS:
        assert metrics[key] is None

    closes = [100.0 + index for index in range(70)]
    closes[-4] = None
    metrics = metrics_for(monkeypatch, make_history(closes))
    assert metrics["return_1d_pct"] is not None
    assert metrics["return_1w_pct"] is None
    assert metrics["return_1m_pct"] is None
    assert metrics["return_3m_pct"] is None

    closes[-4] = float("inf")
    metrics = metrics_for(monkeypatch, make_history(closes))
    assert metrics["return_1w_pct"] is None


def test_ytd_uses_nearby_final_prior_year_close(monkeypatch):
    dates = pd.to_datetime(
        ["2023-12-28", "2023-12-29", "2024-01-02", "2024-01-03"]
    )
    history = make_history([98.0, 100.0, 105.0, 110.0], dates=dates)
    metrics = metrics_for(monkeypatch, history)
    assert metrics["return_ytd_pct"] == pytest.approx(10.0)

    stale_anchor = make_history(
        [100.0, 110.0],
        dates=pd.to_datetime(["2023-12-20", "2024-01-10"]),
    )
    assert metrics_for(monkeypatch, stale_anchor)["return_ytd_pct"] is None

    missing_coverage = make_history(
        [100.0, None, 110.0],
        dates=pd.to_datetime(["2023-12-29", "2024-01-02", "2024-01-03"]),
    )
    assert metrics_for(monkeypatch, missing_coverage)["return_ytd_pct"] is None


def test_complete_one_year_uses_session_boundaries(monkeypatch):
    closes = [100.0 + index for index in range(253)]
    history = make_history(closes, start="2024-01-02")
    history[0]["High"] = 50_000.0
    history[0]["Low"] = -50_000.0

    metrics = metrics_for(monkeypatch, history)

    assert metrics["return_1y_pct"] == pytest.approx(
        (closes[-1] / closes[0] - 1) * 100
    )
    assert metrics["high_52w"] == pytest.approx(history[-1]["High"])
    assert metrics["low_52w"] == pytest.approx(history[1]["Low"])
    assert metrics["max_drawdown_1y_pct"] == pytest.approx(0.0)


def test_252_session_context_accepts_weekend_and_holiday_gaps(monkeypatch):
    dates = [
        pd.Timestamp("2024-01-02"),
        *pd.bdate_range("2024-01-08", periods=251),
    ]
    history = make_history([100.0 + index for index in range(252)], dates=dates)

    metrics = metrics_for(monkeypatch, history)

    assert metrics["high_52w"] is not None
    assert metrics["low_52w"] is not None
    assert metrics["max_drawdown_1y_pct"] == pytest.approx(0.0)


def test_gap_over_seven_days_invalidates_covered_windows(monkeypatch):
    dates = list(pd.bdate_range("2024-01-02", periods=253))
    for index in range(200, len(dates)):
        dates[index] += pd.Timedelta(days=14)
    history = make_history([100.0 + index for index in range(253)], dates=dates)

    metrics = metrics_for(monkeypatch, history)

    assert metrics["return_1y_pct"] is None
    assert metrics["high_52w"] is None
    assert metrics["low_52w"] is None
    assert metrics["max_drawdown_1y_pct"] is None


def test_nonzero_maximum_drawdown(monkeypatch):
    closes = [100.0] * 100 + [120.0] * 40 + [60.0] + [90.0] * 111
    assert len(closes) == 252
    metrics = metrics_for(monkeypatch, make_history(closes))
    assert metrics["max_drawdown_1y_pct"] == pytest.approx(-50.0)


def test_smas_align_and_keep_null_warmup_values(monkeypatch):
    history = make_history([100.0 + index for index in range(220)])
    monkeypatch.setattr(analytics, "get_stock_history", lambda _symbol: history)

    metrics = analytics.get_stock_metrics("TEST")
    series = analytics.get_stock_analytics_series("TEST")["data"]

    assert all(row["SMA20"] is None for row in series[:19])
    assert series[19]["SMA20"] == pytest.approx(109.5)
    assert all(row["SMA50"] is None for row in series[:49])
    assert all(row["SMA200"] is None for row in series[:199])
    assert series[199]["SMA200"] == pytest.approx(199.5)
    assert metrics["sma_20"] == series[-1]["SMA20"]
    assert metrics["sma_50"] == series[-1]["SMA50"]
    assert metrics["sma_200"] == series[-1]["SMA200"]


def test_annualized_volatility_uses_30_returns_and_is_json_safe(monkeypatch):
    closes = [100.0 + index * 0.25 for index in range(40)]
    metrics = metrics_for(monkeypatch, make_history(closes))
    returns = pd.Series(closes[-31:]).pct_change().dropna()
    assert metrics["annualized_volatility_30d_pct"] == pytest.approx(
        returns.std() * math.sqrt(252) * 100
    )

    extreme_return = [5e-324] + [1e308] * 21
    metrics = metrics_for(monkeypatch, make_history(extreme_return))
    assert metrics["return_1m_pct"] is None

    extreme_volatility = [5e-324] + [1e308] * 30
    metrics = metrics_for(monkeypatch, make_history(extreme_volatility))
    assert metrics["annualized_volatility_30d_pct"] is None
    json.dumps(metrics, allow_nan=False)


def test_flat_prices_and_zero_volume_are_handled(monkeypatch):
    metrics = metrics_for(
        monkeypatch,
        make_history([50.0] * 253, volumes=[0] * 252 + [100], flat_range=True),
    )
    for key in (
        "return_1d_pct",
        "return_1w_pct",
        "return_1m_pct",
        "return_3m_pct",
        "return_1y_pct",
        "annualized_volatility_30d_pct",
        "max_drawdown_1y_pct",
    ):
        assert metrics[key] == pytest.approx(0.0)
    assert metrics["range_position_52w_pct"] is None
    assert metrics["average_volume_20d"] == 0.0
    assert metrics["volume_vs_average_20d_pct"] is None

    current_zero = make_history([50.0] * 21, volumes=[100] * 20 + [0])
    metrics = metrics_for(monkeypatch, current_zero)
    assert metrics["volume_vs_average_20d_pct"] == pytest.approx(-100.0)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf")])
def test_finite_number_rejects_nonfinite_values(value):
    assert finite_number(value) is None


def test_canonical_latest_close_truncates_summary_and_series(monkeypatch):
    history = make_history([100.0, 101.0, None, float("inf"), float("-inf")])
    monkeypatch.setattr(analytics, "get_stock_history", lambda _symbol: history)

    metrics = analytics.get_stock_metrics("TEST")
    series = analytics.get_stock_analytics_series("TEST")

    assert metrics["as_of_date"] == str(pd.Timestamp(history[1]["Date"]).date())
    assert metrics["latest_close"] == 101.0
    assert series["as_of_date"] == metrics["as_of_date"]
    assert series["count"] == 2
    assert series["data"][-1]["Date"] == metrics["as_of_date"]
    json.dumps(metrics, allow_nan=False)
    json.dumps(series, allow_nan=False)


def test_nonfinite_ohlcv_and_derived_inputs_never_escape(monkeypatch):
    history = make_history([100.0] * 252)
    history[-1].update(
        {
            "Open": float("nan"),
            "High": float("inf"),
            "Low": float("-inf"),
            "Volume": float("inf"),
        }
    )
    monkeypatch.setattr(analytics, "get_stock_history", lambda _symbol: history)

    metrics = analytics.get_stock_metrics("TEST")
    series = analytics.get_stock_analytics_series("TEST")

    assert metrics["current_volume"] is None
    assert metrics["high_52w"] is None
    assert metrics["low_52w"] is None
    assert metrics["average_volume_20d"] is None
    assert series["data"][-1]["Volume"] is None
    json.dumps(metrics, allow_nan=False)
    json.dumps(series, allow_nan=False)


def test_nonfinite_close_invalidates_sma_return_volatility_and_drawdown(monkeypatch):
    closes = [100.0] * 253
    closes[-4] = float("-inf")
    metrics = metrics_for(monkeypatch, make_history(closes))

    assert metrics["sma_20"] is None
    assert metrics["return_1w_pct"] is None
    assert metrics["annualized_volatility_30d_pct"] is None
    assert metrics["max_drawdown_1y_pct"] is None
    json.dumps(metrics, allow_nan=False)
