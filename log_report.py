"""호출 로그를 집계해 도구별 호출 수, 오류율, 평균 응답 시간과 최근 오류를 보여준다.

실행: python log_report.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from call_log import LOG_PATH


def load_records(path: Path = LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize(records: list[dict]) -> dict:
    stats = defaultdict(lambda: {"calls": 0, "errors": 0, "total_ms": 0.0})
    for r in records:
        s = stats[r["tool"]]
        s["calls"] += 1
        s["total_ms"] += r.get("duration_ms", 0.0)
        if r.get("status") == "error":
            s["errors"] += 1

    return {
        tool: {
            "calls": s["calls"],
            "error_rate_pct": round(s["errors"] / s["calls"] * 100, 1),
            "avg_ms": round(s["total_ms"] / s["calls"], 1),
        }
        for tool, s in sorted(stats.items())
    }


def main() -> None:
    records = load_records()
    if not records:
        print(f"기록이 없습니다: {LOG_PATH}")
        return

    print(f"전체 호출 {len(records)}건\n")
    print(f"{'도구':<14}{'호출 수':>8}{'오류율(%)':>12}{'평균(ms)':>12}")
    for tool, s in summarize(records).items():
        print(f"{tool:<14}{s['calls']:>8}{s['error_rate_pct']:>12}{s['avg_ms']:>12}")

    errors = [r for r in records if r.get("status") == "error"][-5:]
    if errors:
        print("\n최근 오류")
        for r in errors:
            print(f"- {r['ts']} {r['tool']} {r['args']} -> {r['error']}")


if __name__ == "__main__":
    main()
