"""도구 호출 기록(추적 로그).

모든 도구 호출을 logs/tool_calls.jsonl에 한 줄씩 JSON으로 남긴다.
- 언제(ts), 어떤 등급(tier)이, 어떤 도구(tool)를, 어떤 입력(args)으로 호출했는지
- 얼마나 걸렸는지(duration_ms), 성공했는지(status), 실패했다면 왜(error)

stdio 방식 MCP 서버는 표준 출력을 통신에 쓰기 때문에, 로그는 반드시 파일로 남긴다.
"""

from __future__ import annotations

import functools
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Claude 데스크톱은 서버를 다른 작업 폴더에서 실행할 수 있으므로,
# 현재 폴더가 아니라 이 파일 위치를 기준으로 로그 경로를 잡는다.
LOG_PATH = Path(__file__).resolve().parent / "logs" / "tool_calls.jsonl"


def _write(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def logged(func):
    """도구 함수를 감싸 호출 결과를 기록한다. 예외는 기록한 뒤 그대로 다시 던진다."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": func.__name__,
            "tier": os.environ.get("STOCK_MCP_TIER", "enterprise"),
            "args": kwargs or list(args),
        }
        try:
            result = func(*args, **kwargs)
            record["status"] = "ok"
            return result
        except Exception as e:
            record["status"] = "error"
            record["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            _write(record)

    return wrapper
