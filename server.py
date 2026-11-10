"""주식 데이터 MCP 서버.

Claude 같은 MCP 클라이언트가 이 서버에 연결하면, 아래 @mcp.tool()로 등록한
함수들을 '도구'로 보고 필요할 때 호출한다.
모든 도구 호출은 @logged가 logs/tool_calls.jsonl에 기록하고,
실패하면 @friendly_errors가 원인을 Claude가 읽을 수 있는 메시지로 바꿔 전달한다.
"""

import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import microstructure
import policy
import stock
import tiers
from call_log import logged


def friendly_errors(func):
    """예상하지 못한 예외를 ToolError로 바꿔, Claude가 실패 원인을 읽고 사용자에게 설명할 수 있게 한다.

    ToolError가 아닌 예외는 클라이언트에 'Error executing tool'로만 전달되기 때문이다.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except policy.PolicyError as e:
            raise ToolError(f"반출 정책 위반: {e}") from e
        except ValueError as e:
            raise ToolError(str(e)) from e
        except Exception as e:
            raise ToolError(f"시세 조회 중 오류가 발생했습니다 ({type(e).__name__}). 잠시 후 다시 시도해 주세요.") from e

    return wrapper

mcp = MCPServer(
    name="stock-mcp",
    instructions=(
        "주식 시세를 조회하고 간단한 지표로 흐름을 분석하는 도구 모음입니다. "
        "한국 종목은 6자리 코드(예: 005930), 미국 종목은 티커(예: AAPL)로 조회합니다. "
        "틱·호가 데이터는 원본을 반출하지 않는 Compute-to-Data 방식으로, "
        "list_datasets로 데이터셋을 확인한 뒤 파생 지표 도구를 사용합니다."
    ),
)


@mcp.tool()
@friendly_errors
@logged
def get_price(ticker: str) -> dict:
    """종목의 가장 최근 종가와 전일 대비 등락률을 조회합니다.

    Args:
        ticker: 종목 코드. 한국 종목은 6자리 숫자(예: 005930), 미국 종목은 티커(예: AAPL).
    """
    used, df = stock.fetch_history(ticker, days=2)
    return stock.summarize_price(used, df)


@mcp.tool()
@friendly_errors
@logged
def get_history(ticker: str, days: int = 20) -> dict:
    """최근 N 거래일의 일별 종가와 기간 최고가·최저가·수익률을 조회합니다.

    Args:
        ticker: 종목 코드. 한국 종목은 6자리 숫자, 미국 종목은 티커.
        days: 조회할 거래일 수 (기본 20일, 최대 250일).
    """
    days = max(1, min(days, 250))
    used, df = stock.fetch_history(ticker, days=days)
    return stock.summarize_history(used, df)


@mcp.tool()
@friendly_errors
@logged
def analyze(ticker: str, days: int = 60) -> dict:
    """이동평균(MA5·MA20), 변동성, 최대 낙폭으로 최근 추세를 상승·하락·횡보로 요약합니다.

    흐름이나 추세, 변동성을 물으면 이 도구를 사용합니다.

    Args:
        ticker: 종목 코드. 한국 종목은 6자리 숫자, 미국 종목은 티커.
        days: 분석할 거래일 수 (기본 60일, 최소 20일, 최대 250일).
    """
    days = max(20, min(days, 250))
    used, df = stock.fetch_history(ticker, days=days)
    return stock.analyze_trend(used, df)


# ------------------------------------------------------------------ Compute-to-Data
# 아래 도구들은 vault의 원본 틱·호가 이벤트로 계산하지만, 원본은 내보내지 않고 파생값만 반환한다.
# 반환 직전에 policy.enforce_output으로 개별 주문 정보·행 수 제한을 검사한다.


def compute_to_data(func):
    """1) 이용 등급이 이 도구를 쓸 수 있는지 확인하고 2) 결과가 반출 정책을 지키는지 검사한다."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tiers.check_tool(func.__name__)
        result = func(*args, **kwargs)
        policy.enforce_output(result)
        return result

    return wrapper


@mcp.tool()
@friendly_errors
@logged
@compute_to_data
def list_datasets() -> list[dict]:
    """조회 가능한 틱·호가 데이터셋 목록과 제공 지표를 보여줍니다. 원본 이벤트는 제공하지 않습니다."""
    return microstructure.list_datasets()


@mcp.tool()
@friendly_errors
@logged
@compute_to_data
def market_microstructure(
    ticker: str, start: str | None = None, end: str | None = None, window_sec: int = 60
) -> dict:
    """틱·호가 원본으로 계산한 구간별 시장 미시구조 지표를 반환합니다.

    지표: 스프레드(호가 단위 수), 호가 불균형 OBI(-1 매도 우위 ~ +1 매수 우위),
    취소율(취소/접수), 메시지 수, 체결 건수·거래량.
    이벤트가 너무 적은 구간은 개별 주문이 드러날 수 있어 숨깁니다(suppressed).

    Args:
        ticker: 데이터셋 종목 코드 (list_datasets로 확인, 예: DEMO01).
        start: 시작 시각 'HH:MM' (생략하면 장 시작부터).
        end: 끝 시각 'HH:MM' (생략하면 장 끝까지).
        window_sec: 집계 단위(초). 최소 60초.
    """
    session_end = microstructure.session_end(ticker)
    limited_end = tiers.clamp_end(end, session_end)
    if start and limited_end and start >= limited_end:
        raise policy.PolicyError(f"현재 등급은 {limited_end} 이전 데이터만 볼 수 있습니다 (지연 제공).")
    result = microstructure.market_microstructure(ticker, start, limited_end, window_sec)
    result["data_until"] = limited_end or session_end.strftime("%H:%M")
    return result


@mcp.tool()
@friendly_errors
@logged
@compute_to_data
def surveillance_scan(ticker: str, start: str | None = None, end: str | None = None) -> dict:
    """스푸핑(허수 대량 주문 후 빠른 취소) 의심 구간을 찾아 시각·방향·건수·총량만 반환합니다.

    개별 주문 번호와 가격은 반환하지 않습니다.

    Args:
        ticker: 데이터셋 종목 코드 (예: DEMO01).
        start: 시작 시각 'HH:MM' (생략 가능).
        end: 끝 시각 'HH:MM' (생략 가능).
    """
    return microstructure.surveillance_scan(ticker, start, end)


@mcp.tool()
@friendly_errors
@logged
@compute_to_data
def tca_estimate(ticker: str, side: str, qty: int, at: str) -> dict:
    """특정 시각에 시장가 주문을 냈다면 드는 거래 비용(슬리피지)을 추정합니다. Enterprise 전용.

    그 시각의 호가를 재구성해 최우선 호가부터 차례로 체결시킨 평균 체결가를 중간가와 비교합니다.
    결과: 평균 체결가, 슬리피지(bp), 그중 스프레드 비용과 충격 비용, 먹은 호가 단계 수.

    Args:
        ticker: 데이터셋 종목 코드 (예: DEMO01).
        side: 'buy'(매수) 또는 'sell'(매도).
        qty: 주문 수량(주).
        at: 주문 시각 'HH:MM'.
    """
    return microstructure.tca_estimate(ticker, side, qty, at)


@mcp.tool()
@friendly_errors
@logged
@compute_to_data
def get_access_info() -> dict:
    """현재 이용 등급(EDU/Enterprise), 데이터 지연 시간, 사용 가능한 도구 목록을 보여줍니다."""
    return tiers.access_info()


if __name__ == "__main__":
    # stdio 방식: Claude 데스크톱이 이 파일을 실행하고 표준 입출력으로 통신한다.
    # 그래서 print()로 표준 출력에 아무거나 찍으면 통신이 깨진다. 디버깅 출력은 stderr로 보낸다.
    mcp.run()
