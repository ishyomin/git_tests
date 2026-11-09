"""네트워크 없이 가공 로직만 검사하는 테스트. 실행: pytest"""

import pandas as pd
import pytest

import stock


def make_df(closes):
    idx = pd.date_range("2026-11-02", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "Close": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Volume": [1000] * len(closes),
        },
        index=idx,
    )


def test_normalize_korean_code():
    assert stock.normalize_ticker("005930") == ["005930.KS", "005930.KQ"]


def test_normalize_us_ticker():
    assert stock.normalize_ticker(" aapl ") == ["AAPL"]


def test_summarize_price_change():
    result = stock.summarize_price("TEST", make_df([100.0, 110.0]))
    assert result["close"] == 110.0
    assert result["change"] == 10.0
    assert result["change_pct"] == 10.0


def test_summarize_price_single_day_has_no_change():
    result = stock.summarize_price("TEST", make_df([100.0]))
    assert "change" not in result


def test_summarize_history():
    result = stock.summarize_history("TEST", make_df([100.0, 90.0, 120.0]))
    assert result["days"] == 3
    assert result["high"] == 121.0
    assert result["low"] == 89.0
    assert result["return_pct"] == 20.0
    assert len(result["daily"]) == 3


def test_empty_data_raises():
    with pytest.raises(ValueError):
        stock.summarize_price("TEST", make_df([]))
