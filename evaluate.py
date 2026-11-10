"""스푸핑 탐지 규칙의 성능 평가.

시드(seed)를 바꿔 가상 데이터를 여러 번 새로 만들고, 탐지 결과를 정답(labels)과 비교해
정밀도·재현율·F1을 구한다. 규칙의 기준값(대량 주문 배수)을 바꿔 가며 비교한다.

- 정밀도(precision): 탐지한 것 중 진짜 스푸핑 비율. 낮으면 오탐이 많다.
- 재현율(recall): 진짜 스푸핑 중 찾아낸 비율. 낮으면 놓치는 게 많다.
- F1: 둘의 조화평균.

탐지 구간과 정답 구간의 방향이 같고 시간이 겹치면 맞힌 것으로 본다.
정답은 평가에만 쓰고 MCP 도구로는 절대 노출하지 않는다.

실행: python evaluate.py
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import microstructure
import simulator

SEEDS = [1, 2, 3, 4, 5]
MULTIPLES = [3, 5, 10, 20]


def _hit(alert: dict, label: dict, day) -> bool:
    a0 = datetime.combine(day, datetime.strptime(alert["start"], "%H:%M:%S").time())
    a1 = datetime.combine(day, datetime.strptime(alert["end"], "%H:%M:%S").time())
    l0, l1 = datetime.fromisoformat(label["start"]), datetime.fromisoformat(label["end"])
    return alert["side"] == label["side"] and a0 <= l1 and l0 <= a1


def evaluate(multiples=MULTIPLES, seeds=SEEDS) -> list[dict]:
    datasets = [simulator.simulate(seed=s) for s in seeds]
    original = microstructure.VAULT
    results = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            microstructure.VAULT = Path(tmp)
            for m in multiples:
                tp = fp = fn = 0
                for df, labels in datasets:
                    df.to_csv(Path(tmp) / "EVAL_events.csv", index=False)
                    microstructure._load.cache_clear()
                    alerts = microstructure.surveillance_scan("EVAL", None, None, large_multiple=m)["alerts"]
                    day = df["ts"].iloc[0].date()
                    matched = sum(any(_hit(a, l, day) for a in alerts) for l in labels)
                    true_alerts = sum(any(_hit(a, l, day) for l in labels) for a in alerts)
                    tp += matched
                    fn += len(labels) - matched
                    fp += len(alerts) - true_alerts
                precision = tp / (tp + fp) if tp + fp else 0.0
                recall = tp / (tp + fn) if tp + fn else 0.0
                f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
                results.append({"multiple": m, "tp": tp, "fp": fp, "fn": fn,
                                "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)})
    finally:
        microstructure.VAULT = original
        microstructure._load.cache_clear()
    return results


def main() -> None:
    print(f"가상 데이터 {len(SEEDS)}세트 (각 스푸핑 8건)로 평가\n")
    print(f"{'배수':>4}{'TP':>5}{'FP':>5}{'FN':>5}{'정밀도':>9}{'재현율':>9}{'F1':>8}")
    for r in evaluate():
        print(f"{r['multiple']:>4}{r['tp']:>5}{r['fp']:>5}{r['fn']:>5}"
              f"{r['precision']:>9}{r['recall']:>9}{r['f1']:>8}")


if __name__ == "__main__":
    main()
