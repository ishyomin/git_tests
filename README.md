# stock-mcp

주식 시세를 조회하고 간단한 지표로 흐름을 분석하는 **MCP(Model Context Protocol) 서버**입니다.
Claude 데스크톱에 연결하면 Claude가 질문에 맞는 도구를 골라 호출하고, 실제 시세 데이터를 바탕으로 답합니다.

> 금융 공모전에서 기획한 "실시간 주식 데이터를 LLM이 자동 분석하는 시스템" 아이디어를
> 직접 동작하는 최소 버전으로 구현한 프로젝트입니다.

## 실행 예시

<!-- 스크린샷 파일을 docs/ 폴더에 넣고 아래 경로를 맞춰 주세요 -->
![Claude 데스크톱 실행 예시](docs/example.png)

## 도구

| 도구 | 설명 |
|---|---|
| `get_price` | 가장 최근 종가와 전일 대비 등락률 |
| `get_history` | 최근 N 거래일의 일별 종가, 기간 최고가·최저가·수익률 |
| `analyze` | 이동평균(MA5·MA20), 변동성, 최대 낙폭(MDD)으로 상승·하락·횡보 판단 |

한국 종목은 6자리 코드(예: `005930`, 코스피 → 코스닥 순으로 조회), 미국 종목은 티커(예: `AAPL`)로 조회합니다.
시세 데이터는 [yfinance](https://github.com/ranaroussi/yfinance)로 가져옵니다.

## 구조

```
server.py       MCP 서버. 도구를 등록하고 오류를 Claude가 읽을 수 있는 메시지로 변환
stock.py        시세 조회와 지표 계산 (MCP와 분리해 네트워크 없이 테스트 가능)
call_log.py     모든 도구 호출을 logs/tool_calls.jsonl에 기록 (입력, 소요 시간, 성공 여부, 오류)
log_report.py   호출 로그를 도구별 호출 수·오류율·평균 응답 시간으로 집계
tests/          지표 계산과 로그 기록 테스트
```

### 호출 추적
도구가 호출될 때마다 아래처럼 한 줄씩 기록되고, `python log_report.py`로 집계할 수 있습니다.

```json
{"ts": "2026-11-10T01:28:37+00:00", "tool": "analyze", "args": {"ticker": "005930", "days": 60}, "status": "ok", "duration_ms": 812.4}
```

```
도구              호출 수   오류율(%)    평균(ms)
analyze              3        0.0       790.2
get_price            2       50.0       612.5
```

## 설치 및 실행 (Windows)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
```

Claude 데스크톱 설정 파일(`claude_desktop_config.json`)에 서버를 등록합니다.

```json
{
  "mcpServers": {
    "stock-mcp": {
      "command": "C:\\경로\\stock-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\경로\\stock-mcp\\server.py"]
    }
  }
}
```

Claude 데스크톱을 완전히 종료했다가 다시 실행한 뒤 "005930 최근 흐름 분석해줘"처럼 질문합니다.

## 참고
- 지표는 학습용 단순 계산이며 투자 판단의 근거가 아닙니다.
- stdio 방식 MCP 서버는 표준 출력을 통신에 사용하므로, 로그는 표준 출력이 아닌 파일로 남깁니다.
