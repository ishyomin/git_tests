"""주식 데이터 MCP 서버.

Claude 같은 MCP 클라이언트가 이 서버에 연결하면, 아래 @mcp.tool()로 등록한
함수들을 '도구'로 보고 필요할 때 호출한다.
"""

from mcp.server.mcpserver import MCPServer

import stock

mcp = MCPServer(
    name="stock-mcp",
    instructions=(
        "주식 시세를 조회하는 도구 모음입니다. "
        "한국 종목은 6자리 코드(예: 005930), 미국 종목은 티커(예: AAPL)로 조회합니다."
    ),
)


@mcp.tool()
def get_price(ticker: str) -> dict:
    """종목의 가장 최근 종가와 전일 대비 등락률을 조회합니다.

    Args:
        ticker: 종목 코드. 한국 종목은 6자리 숫자(예: 005930), 미국 종목은 티커(예: AAPL).
    """
    used, df = stock.fetch_history(ticker, days=2)
    return stock.summarize_price(used, df)


@mcp.tool()
def get_history(ticker: str, days: int = 20) -> dict:
    """최근 N 거래일의 일별 종가와 기간 최고가·최저가·수익률을 조회합니다.

    Args:
        ticker: 종목 코드. 한국 종목은 6자리 숫자, 미국 종목은 티커.
        days: 조회할 거래일 수 (기본 20일, 최대 250일).
    """
    days = max(1, min(days, 250))
    used, df = stock.fetch_history(ticker, days=days)
    return stock.summarize_history(used, df)


if __name__ == "__main__":
    # stdio 방식: Claude 데스크톱이 이 파일을 실행하고 표준 입출력으로 통신한다.
    # 그래서 print()로 표준 출력에 아무거나 찍으면 통신이 깨진다. 디버깅 출력은 stderr로 보낸다.
    mcp.run()
