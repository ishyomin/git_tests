"""이용 등급(EDU / Enterprise)별 권한 확인.

공모전 기획의 이원 라인업을 구현한다.
- EDU: 교육·연구용. 20분 지연된 데이터만, 기본 지표 도구만 사용 가능.
- ENTERPRISE: 실시간 데이터, 서베일런스·TCA까지 모든 도구 사용 가능.

등급은 Claude 데스크톱 설정의 환경 변수 STOCK_MCP_TIER로 정한다 (기본값: enterprise).
실제 서비스라면 API 키나 계약 정보로 등급을 확인하겠지만, 여기서는 설정값으로 대신한다.
"""

from __future__ import annotations

import os
from datetime import timedelta

from policy import PolicyError

TIERS = {
    "edu": {
        "delay_min": 20,
        "tools": {"list_datasets", "market_microstructure", "get_access_info"},
    },
    "enterprise": {
        "delay_min": 0,
        "tools": {"list_datasets", "market_microstructure", "surveillance_scan", "tca_estimate", "get_access_info"},
    },
}


def current() -> str:
    tier = os.environ.get("STOCK_MCP_TIER", "enterprise").strip().lower()
    if tier not in TIERS:
        raise PolicyError(f"알 수 없는 이용 등급입니다: {tier}")
    return tier


def check_tool(tool: str) -> None:
    tier = current()
    if tool not in TIERS[tier]["tools"]:
        raise PolicyError(f"{tier.upper()} 등급에서는 {tool} 도구를 사용할 수 없습니다. Enterprise 등급이 필요합니다.")


def cutoff(session_end):
    """이 등급이 볼 수 있는 마지막 시각. EDU는 '현재'(세션 마지막 시각)보다 20분 전까지만."""
    return session_end - timedelta(minutes=TIERS[current()]["delay_min"])


def clamp_end(end: str | None, session_end) -> str | None:
    """요청한 끝 시각을 등급의 지연 한도 안으로 줄인다. 지연이 없으면 그대로 둔다."""
    if TIERS[current()]["delay_min"] == 0:
        return end
    limit = cutoff(session_end).strftime("%H:%M")
    return limit if end is None or end > limit else end


def access_info() -> dict:
    tier = current()
    return {
        "tier": tier,
        "delay_min": TIERS[tier]["delay_min"],
        "tools": sorted(TIERS[tier]["tools"]),
    }
