"""원본 반출 차단 규칙 (Compute-to-Data 정책).

MCP 도구는 vault의 원본 이벤트로 계산은 하되, 밖으로는 집계된 파생값만 내보낸다.
아래 규칙을 모든 도구 결과에 적용해, 규칙을 어기는 결과는 아예 반환하지 않는다.

1. 집계 단위는 최소 MIN_WINDOW_SEC초. 너무 짧게 자르면 개별 주문이 드러난다.
2. 한 구간의 이벤트가 MIN_EVENTS건보다 적으면 값을 숨긴다(suppressed).
   이벤트가 몇 건뿐인 구간의 평균은 사실상 개별 주문 정보이기 때문이다.
3. 결과에 주문 번호처럼 개별 주문을 식별할 수 있는 키가 있으면 안 된다.
4. 한 번에 내보내는 행 수는 MAX_ROWS를 넘을 수 없다.
"""

from __future__ import annotations

MIN_WINDOW_SEC = 60
MIN_EVENTS = 20
MAX_ROWS = 200
FORBIDDEN_KEYS = {"order_id"}


class PolicyError(Exception):
    """정책 위반. 도구는 이 경우 결과 대신 위반 사유를 돌려준다."""


def check_window(window_sec: int) -> None:
    if window_sec < MIN_WINDOW_SEC:
        raise PolicyError(f"집계 단위는 최소 {MIN_WINDOW_SEC}초입니다. (요청: {window_sec}초)")


def enforce_output(obj, _path: str = "result") -> None:
    """결과 전체를 훑어 금지 키와 행 수 제한을 검사한다. 위반하면 PolicyError."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                raise PolicyError(f"개별 주문 식별 정보({k})는 반출할 수 없습니다. 위치: {_path}")
            enforce_output(v, f"{_path}.{k}")
    elif isinstance(obj, list):
        if len(obj) > MAX_ROWS:
            raise PolicyError(f"한 번에 {MAX_ROWS}행을 넘길 수 없습니다. 기간을 줄이거나 집계 단위를 늘려 주세요.")
        for i, v in enumerate(obj):
            enforce_output(v, f"{_path}[{i}]")
