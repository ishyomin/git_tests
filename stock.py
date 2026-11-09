"""주식 데이터 조회 및 가공 함수.

MCP와 무관한 순수 로직만 둔다. 데이터를 가져오는 부분(fetch_history)과
가공하는 부분(summarize_*)을 나눠서, 가공 로직은 네트워크 없이 테스트할 수 있게 했다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import yfinance as yf


def normalize_ticker(ticker: str) -> list[str]:
    """사용자가 입력한 종목 코드를 yfinance가 이해하는 후보 목록으로 바꾼다.

    - 6자리 숫자(예: 005930)는 한국 종목으로 보고 코스피(.KS), 코스닥(.KQ) 순으로 시도한다.
    - 그 외(AAPL, 005930.KS 등)는 그대로 사용한다.
    """
    t = ticker.strip().upper()
    if t.isdigit() and len(t) == 6:
        return [f"{t}.KS", f"{t}.KQ"]
    return [t]


def fetch_history(ticker: str, days: int) -> tuple[str, pd.DataFrame]:
    """최근 days 거래일의 일별 시세를 가져온다. (실제 사용한 티커, 데이터프레임)을 반환."""
    if days < 1:
        raise ValueError("days는 1 이상이어야 합니다.")

    # 주말·휴장일을 고려해 달력 기준으로 넉넉하게 조회한 뒤 마지막 days개만 남긴다.
    start = date.today() - timedelta(days=days * 2 + 10)
    for candidate in normalize_ticker(ticker):
        df = yf.Ticker(candidate).history(start=start.isoformat(), auto_adjust=False)
        if not df.empty:
            return candidate, df.tail(days)
    raise ValueError(f"'{ticker}'에 해당하는 시세 데이터를 찾지 못했습니다.")


def summarize_price(ticker: str, df: pd.DataFrame) -> dict:
    """가장 최근 종가와 전일 대비 등락을 계산한다."""
    if df.empty:
        raise ValueError("시세 데이터가 비어 있습니다.")

    last = df.iloc[-1]
    result = {
        "ticker": ticker,
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": round(float(last["Close"]), 2),
        "volume": int(last["Volume"]),
    }
    if len(df) >= 2:
        prev_close = float(df["Close"].iloc[-2])
        change = float(last["Close"]) - prev_close
        result["change"] = round(change, 2)
        result["change_pct"] = round(change / prev_close * 100, 2)
    return result


def summarize_history(ticker: str, df: pd.DataFrame) -> dict:
    """기간 동안의 일별 종가 목록과 최고·최저·기간 수익률을 정리한다."""
    if df.empty:
        raise ValueError("시세 데이터가 비어 있습니다.")

    closes = df["Close"]
    first, last = float(closes.iloc[0]), float(closes.iloc[-1])
    return {
        "ticker": ticker,
        "start": df.index[0].strftime("%Y-%m-%d"),
        "end": df.index[-1].strftime("%Y-%m-%d"),
        "days": len(df),
        "high": round(float(df["High"].max()), 2),
        "low": round(float(df["Low"].min()), 2),
        "return_pct": round((last - first) / first * 100, 2),
        "daily": [
            {"date": idx.strftime("%Y-%m-%d"), "close": round(float(c), 2)}
            for idx, c in closes.items()
        ],
    }
