"""가상 틱·호가 이벤트 생성기.

실제 KRX 틱 데이터는 정보이용계약 없이 쓸 수 없으므로, 비슷한 형태의 가상 데이터를 만든다.
만들어진 원본은 vault/ 폴더에만 저장하고, MCP 도구는 이 원본을 절대 그대로 내보내지 않는다.

이벤트 종류
- add:    지정가 주문 접수 (매수 bid / 매도 ask)
- cancel: 주문 취소
- trade:  체결 (시장가 주문이 반대편 최우선 호가와 체결)

테스트·평가를 위해 일부러 '스푸핑' 패턴을 섞는다.
또 오탐을 만들 수 있는 '정상 대량 주문'(기관이 큰 주문을 1~3건 냈다가 가격 조정 등으로 곧 취소하거나
그대로 두는 경우)도 섞어서, 탐지 기준을 너무 낮추면 오탐이 생기고 너무 높이면 놓치도록 했다.
스푸핑: 실제로 체결할 생각이 없는 대량 주문을 한쪽에 깔아 가격을 움직인 뒤, 몇 초 안에 모두 취소하는 행위.
어디에 섞었는지는 vault/labels.json에 정답으로 따로 저장한다.

실행: python simulator.py
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

VAULT = Path(__file__).resolve().parent / "vault"
TICK = 100  # 호가 단위(원)


def simulate(
    ticker: str = "DEMO01",
    start: str = "2026-11-10 09:00:00",
    minutes: int = 120,
    n_spoofs: int = 8,
    n_decoys: int = 25,
    seed: int = 42,
) -> tuple[pd.DataFrame, list[dict]]:
    rng = random.Random(seed)
    t0 = datetime.fromisoformat(start)
    end = t0 + timedelta(minutes=minutes)

    mid = 70_000
    book: dict[int, dict] = {}  # order_id -> {side, price, qty}
    events: list[dict] = []
    next_id = 1

    def emit(ts, etype, side, price, qty, oid):
        events.append(
            {"ts": ts, "ticker": ticker, "type": etype, "side": side,
             "price": price, "qty": qty, "order_id": oid}
        )

    def best(side):
        prices = [o["price"] for o in book.values() if o["side"] == side]
        if not prices:
            return None
        return max(prices) if side == "bid" else min(prices)

    def add(ts, side, price, qty):
        nonlocal next_id
        oid = next_id
        next_id += 1
        book[oid] = {"side": side, "price": price, "qty": qty}
        emit(ts, "add", side, price, qty, oid)
        return oid

    def cancel(ts, oid):
        o = book.pop(oid)
        emit(ts, "cancel", o["side"], o["price"], o["qty"], oid)

    def trade(ts, aggressor_side, qty):
        """aggressor_side가 'buy'면 매도 호가(ask)를 먹는다."""
        rest_side = "ask" if aggressor_side == "buy" else "bid"
        while qty > 0:
            p = best(rest_side)
            if p is None:
                return
            # 같은 가격이면 먼저 들어온 주문부터 체결 (가격·시간 우선)
            oid = min(i for i, o in book.items() if o["side"] == rest_side and o["price"] == p)
            o = book[oid]
            fill = min(qty, o["qty"])
            emit(ts, "trade", rest_side, p, fill, oid)
            o["qty"] -= fill
            qty -= fill
            if o["qty"] == 0:
                del book[oid]

    # 스푸핑을 넣을 시각을 미리 정한다 (시작·끝 5분은 제외, 서로 5분 이상 떨어지게)
    spoof_times: list[datetime] = []
    while len(spoof_times) < n_spoofs:
        cand = t0 + timedelta(seconds=rng.uniform(300, minutes * 60 - 300))
        if all(abs((cand - s).total_seconds()) > 300 for s in spoof_times):
            spoof_times.append(cand)
    spoof_times.sort()
    labels: list[dict] = []

    # 정상 대량 주문 시각 (스푸핑과 60초 이상 떨어지게)
    decoy_times: list[datetime] = []
    while len(decoy_times) < n_decoys:
        cand = t0 + timedelta(seconds=rng.uniform(60, minutes * 60 - 60))
        if all(abs((cand - s).total_seconds()) > 60 for s in spoof_times + decoy_times):
            decoy_times.append(cand)
    decoy_times.sort()

    # 초기 호가 깔기
    for i in range(1, 6):
        for _ in range(3):
            add(t0, "bid", mid - i * TICK, rng.randint(10, 80))
            add(t0, "ask", mid + i * TICK, rng.randint(10, 80))

    ts = t0
    while ts < end:
        ts += timedelta(seconds=rng.expovariate(4.0))  # 평균 초당 4건

        # 예정된 스푸핑 실행
        if spoof_times and ts >= spoof_times[0]:
            s_start = spoof_times.pop(0)
            side = rng.choice(["bid", "ask"])
            bb, ba = best("bid") or mid - TICK, best("ask") or mid + TICK
            spoof_ids = []
            t = ts
            for k in range(rng.randint(4, 6)):
                t += timedelta(milliseconds=rng.randint(50, 250))
                price = bb - k * TICK if side == "bid" else ba + k * TICK
                spoof_ids.append(add(t, side, price, rng.randint(500, 1000)))
            # 반대편으로 소량 체결해 이득을 본다
            t += timedelta(milliseconds=rng.randint(300, 900))
            trade(t, "sell" if side == "bid" else "buy", rng.randint(5, 20))
            # 2~5초 안에 대량 주문을 모두 취소
            t += timedelta(seconds=rng.uniform(2, 5))
            for oid in spoof_ids:
                if oid in book:
                    t += timedelta(milliseconds=rng.randint(20, 120))
                    cancel(t, oid)
            labels.append({"start": s_start.isoformat(), "end": t.isoformat(), "side": side})
            ts = t
            continue

        # 정상 대량 주문: 1~3건을 내고, 절반 이상은 1~8초 안에 취소, 나머지는 그대로 둔다
        if decoy_times and ts >= decoy_times[0]:
            decoy_times.pop(0)
            side = rng.choice(["bid", "ask"])
            bb, ba = best("bid") or mid - TICK, best("ask") or mid + TICK
            t = ts
            ids = []
            for k in range(rng.randint(1, 3)):
                t += timedelta(milliseconds=rng.randint(100, 1500))
                price = bb - k * TICK if side == "bid" else ba + k * TICK
                ids.append(add(t, side, price, rng.randint(100, 700)))
            if rng.random() < 0.6:
                t += timedelta(seconds=rng.uniform(1, 8))
                for oid in ids:
                    if oid in book:
                        t += timedelta(milliseconds=rng.randint(50, 400))
                        cancel(t, oid)
            ts = t
            continue

        r = rng.random()
        bb, ba = best("bid"), best("ask")
        if bb is None or ba is None:
            mid_now = mid
        else:
            mid_now = (bb + ba) // 2 // TICK * TICK

        if r < 0.50:
            side = rng.choice(["bid", "ask"])
            offset = rng.randint(0, 4) * TICK
            gap = (ba - bb) if bb and ba else 0
            if gap > TICK and rng.random() < 0.6:
                # 호가 사이가 벌어져 있으면 한 단계 안쪽으로 주문을 넣어 스프레드를 좁힌다
                price = bb + TICK if side == "bid" else ba - TICK
            elif side == "bid":
                price = (bb if bb else mid_now - TICK) - offset
            else:
                price = (ba if ba else mid_now + TICK) + offset
            add(ts, side, price, rng.randint(1, 60))
        elif r < 0.88 and book:
            cancel(ts, rng.choice(list(book)))
        else:
            trade(ts, rng.choice(["buy", "sell"]), rng.randint(1, 40))

    df = pd.DataFrame(events)
    df["ts"] = pd.to_datetime(df["ts"])
    return df, labels


def main() -> None:
    VAULT.mkdir(exist_ok=True)
    df, labels = simulate()
    df.to_csv(VAULT / "DEMO01_events.csv", index=False)
    (VAULT / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(f"이벤트 {len(df):,}건, 스푸핑 {len(labels)}건 -> {VAULT}")


if __name__ == "__main__":
    main()
