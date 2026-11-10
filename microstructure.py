"""vault 원본 이벤트로 시장 미시구조 지표와 이상거래 신호를 계산한다.

여기 있는 함수는 원본에 직접 접근하지만, 반환값은 모두 집계된 파생값이다.
반환 직전에 server.py가 policy.enforce_output으로 한 번 더 검사한다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time
from functools import lru_cache
from pathlib import Path

import pandas as pd

import policy

VAULT = Path(__file__).resolve().parent / "vault"
DEPTH = 5  # OBI 계산에 쓰는 호가 단계 수


# ---------------------------------------------------------------- 원본 접근 (외부 비공개)

@lru_cache(maxsize=8)
def _load(ticker: str) -> pd.DataFrame:
    path = VAULT / f"{ticker.upper()}_events.csv"
    if not path.exists():
        raise ValueError(f"'{ticker}' 데이터셋이 없습니다. list_datasets로 사용 가능한 종목을 확인해 주세요.")
    df = pd.read_csv(path, parse_dates=["ts"])
    return df.sort_values("ts", kind="stable").reset_index(drop=True)


def _slice(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    """'HH:MM' 형식의 시각으로 장중 구간을 자른다."""
    day = df["ts"].iloc[0].date()

    def at(hhmm: str) -> datetime:
        try:
            return datetime.combine(day, time.fromisoformat(hhmm))
        except ValueError as e:
            raise ValueError(f"시각은 'HH:MM' 형식이어야 합니다. (입력: {hhmm})") from e

    if start:
        df = df[df["ts"] >= at(start)]
    if end:
        df = df[df["ts"] < at(end)]
    if df.empty:
        raise ValueError("해당 구간에 데이터가 없습니다.")
    return df


def _replay_snapshots(df_all: pd.DataFrame, sample_times: list[pd.Timestamp]) -> list[dict]:
    """처음부터 이벤트를 다시 재생해 각 시점의 호가 상태(최우선 호가, 상위 5단계 잔량)를 구한다."""
    levels = {"bid": defaultdict(int), "ask": defaultdict(int)}
    snaps = []
    rows = df_all[["ts", "type", "side", "price", "qty"]].itertuples(index=False)
    pending = next(rows, None)
    for t in sample_times:
        while pending is not None and pending.ts < t:
            sign = 1 if pending.type == "add" else -1
            lv = levels[pending.side]
            lv[pending.price] += sign * pending.qty
            if lv[pending.price] <= 0:
                del lv[pending.price]
            pending = next(rows, None)
        bids = sorted(levels["bid"].items(), reverse=True)[:DEPTH]
        asks = sorted(levels["ask"].items())[:DEPTH]
        snaps.append({"bids": bids, "asks": asks})
    return snaps


# ---------------------------------------------------------------- 파생값 (외부 공개)

def list_datasets() -> list[dict]:
    """반출 가능한 정보만 담은 데이터 카탈로그. 원본 경로나 건수는 내보내지 않는다."""
    result = []
    for path in sorted(VAULT.glob("*_events.csv")):
        df = _load(path.name.removesuffix("_events.csv"))
        result.append(
            {
                "ticker": df["ticker"].iloc[0],
                "date": df["ts"].iloc[0].strftime("%Y-%m-%d"),
                "session": f"{df['ts'].iloc[0]:%H:%M} ~ {df['ts'].iloc[-1]:%H:%M}",
                "metrics": ["spread", "obi", "cancel_ratio", "message_rate", "surveillance"],
                "note": "가상 데이터입니다. 원본 이벤트는 반출되지 않습니다.",
            }
        )
    return result


def market_microstructure(ticker: str, start: str | None, end: str | None, window_sec: int) -> dict:
    """구간별 스프레드, 호가 불균형(OBI), 취소율, 메시지 수를 집계한다.

    - spread_ticks: 최우선 매도호가 - 최우선 매수호가 (호가 단위 수). 작을수록 거래 비용이 낮다.
    - obi: (상위 5단계 매수 잔량 - 매도 잔량) / 합계. +1에 가까우면 매수 우위, -1이면 매도 우위.
    - cancel_ratio: 취소 건수 / 접수 건수. 비정상적으로 높으면 허수 주문을 의심할 수 있다.
    - messages: 구간 내 접수·취소·체결 이벤트 수 (메시지 과밀도).
    """
    policy.check_window(window_sec)
    df_all = _load(ticker)
    df = _slice(df_all, start, end)

    buckets = df["ts"].dt.floor(f"{window_sec}s")
    groups = list(df.groupby(buckets))
    ends = [b + pd.Timedelta(seconds=window_sec) for b, _ in groups]
    snaps = _replay_snapshots(df_all, ends)

    rows = []
    for (bucket, g), snap in zip(groups, snaps):
        row = {"window_start": bucket.strftime("%H:%M:%S"), "messages": len(g)}
        if len(g) < policy.MIN_EVENTS:
            row["suppressed"] = True
            rows.append(row)
            continue
        adds = int((g["type"] == "add").sum())
        cancels = int((g["type"] == "cancel").sum())
        trades = g[g["type"] == "trade"]
        bid_vol = sum(q for _, q in snap["bids"])
        ask_vol = sum(q for _, q in snap["asks"])
        spread = None
        if snap["bids"] and snap["asks"]:
            spread = (snap["asks"][0][0] - snap["bids"][0][0]) // 100
        row.update(
            {
                "spread_ticks": spread,
                "obi": round((bid_vol - ask_vol) / (bid_vol + ask_vol), 3) if bid_vol + ask_vol else None,
                "cancel_ratio": round(cancels / adds, 3) if adds else None,
                "trades": len(trades),
                "volume": int(trades["qty"].sum()),
            }
        )
        rows.append(row)

    return {"ticker": ticker.upper(), "window_sec": window_sec, "rows": rows}


def surveillance_scan(
    ticker: str,
    start: str | None,
    end: str | None,
    large_multiple: float = 10.0,
    max_lifetime_sec: float = 10.0,
    min_orders: int = 3,
) -> dict:
    """스푸핑 의심 구간을 찾는다.

    규칙: 평소 주문 수량의 large_multiple배 이상인 대량 주문이
    체결 없이 max_lifetime_sec초 안에 취소되고, 같은 방향으로 min_orders건 이상 몰려 있으면 의심 구간.
    개별 주문 번호나 가격은 내보내지 않고, 구간·방향·건수·총량만 반환한다.
    """
    df = _slice(_load(ticker), start, end)
    adds = df[df["type"] == "add"].set_index("order_id")
    threshold = adds["qty"].median() * large_multiple

    filled = set(df.loc[df["type"] == "trade", "order_id"])
    cancels = df[df["type"] == "cancel"].set_index("order_id")

    suspects = []
    for oid, a in adds[adds["qty"] >= threshold].iterrows():
        if oid in filled or oid not in cancels.index:
            continue
        lifetime = (cancels.at[oid, "ts"] - a["ts"]).total_seconds()
        if lifetime <= max_lifetime_sec:
            suspects.append({"ts": a["ts"], "end": cancels.at[oid, "ts"], "side": a["side"],
                             "qty": int(a["qty"]), "lifetime": lifetime})

    # 같은 방향, 10초 이내로 이어지는 의심 주문을 하나의 구간으로 묶는다
    suspects.sort(key=lambda s: s["ts"])
    clusters: list[list[dict]] = []
    for s in suspects:
        if clusters and clusters[-1][-1]["side"] == s["side"] and \
                (s["ts"] - clusters[-1][-1]["ts"]).total_seconds() <= max_lifetime_sec:
            clusters[-1].append(s)
        else:
            clusters.append([s])

    alerts = []
    for c in clusters:
        if len(c) < min_orders:
            continue
        alerts.append(
            {
                "start": c[0]["ts"].strftime("%H:%M:%S"),
                "end": max(s["end"] for s in c).strftime("%H:%M:%S"),
                "side": c[0]["side"],
                "orders": len(c),
                "total_qty": sum(s["qty"] for s in c),
                "avg_lifetime_sec": round(sum(s["lifetime"] for s in c) / len(c), 1),
            }
        )

    return {
        "ticker": ticker.upper(),
        "rule": f"주문 수량 중앙값의 {large_multiple:g}배 이상 주문이 {max_lifetime_sec:g}초 안에 체결 없이 취소, "
                f"같은 방향 {min_orders}건 이상",
        "alerts": alerts,
    }
