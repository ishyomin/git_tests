# stock-mcp

주식 시세를 조회하고 간단한 지표로 흐름을 분석하는 **MCP(Model Context Protocol) 서버**입니다.
Claude 데스크톱에 연결하면 Claude가 질문에 맞는 도구를 골라 호출하고, 실제 시세 데이터를 바탕으로 답합니다.

> 코스콤 공모전에서 기획한 **"MCP 기반 Compute-to-Data 금융데이터 플랫폼"**을
> 직접 동작하는 최소 버전으로 구현한 프로젝트입니다.
> 틱·호가 원본은 규제·계약상 외부로 반출하기 어렵기 때문에, 원본은 서버 안(vault)에 두고
> MCP 도구는 계산된 **파생 지표만** 반환합니다.

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

### Compute-to-Data 도구 (틱·호가 데이터)

| 도구 | 반환하는 파생값 |
|---|---|
| `list_datasets` | 데이터셋 목록과 제공 지표 (원본 경로·건수는 비공개) |
| `market_microstructure` | 구간별 스프레드, 호가 불균형(OBI), 취소율, 메시지 수, 체결량 |
| `surveillance_scan` | 스푸핑 의심 구간의 시각·방향·건수·총량 (주문 번호·가격 비공개) |
| `tca_estimate` | 특정 시각 시장가 주문의 예상 거래 비용: 평균 체결가, 슬리피지·스프레드·충격 비용(bp) |
| `get_access_info` | 현재 이용 등급, 데이터 지연 시간, 사용 가능한 도구 |

**이용 등급** (`tiers.py`, 설정의 환경 변수 `STOCK_MCP_TIER`)

| 등급 | 데이터 | 사용 가능한 도구 |
|---|---|---|
| `edu` | 20분 지연 | `list_datasets`, `market_microstructure` |
| `enterprise` (기본) | 실시간 | 전체 (서베일런스, TCA 포함) |

권한이 없는 도구를 호출하면 결과 대신 정책 위반 사유를 반환하고, 모든 호출은 등급과 함께 로그에 남습니다.

```
[vault: 원본 틱·호가 이벤트]  →  microstructure.py (내부 계산)  →  policy.py (반출 검사)  →  Claude
       외부 반출 불가                 파생값만 생성                  위반 시 차단
```

**반출 정책** (`policy.py`)
1. 집계 단위는 최소 60초. 더 짧으면 개별 주문이 드러납니다.
2. 이벤트가 20건 미만인 구간은 값을 숨깁니다(`suppressed`).
3. 주문 번호 등 개별 주문 식별 정보는 결과에 포함될 수 없습니다.
4. 한 번에 200행을 넘겨 반환할 수 없습니다.

**데이터**: 실제 KRX 틱 데이터는 정보이용계약이 필요하므로, `simulator.py`가 만든 **가상 데이터**를 사용합니다.
평가를 위해 스푸핑 패턴(대량 주문을 깔았다가 2~5초 안에 모두 취소)과, 오탐을 유발하는 정상 대량 주문(1~3건 냈다가 곧 취소하거나 유지)을 섞고, 정답은 따로 저장해 탐지 결과와 비교합니다.

**탐지 성능** (`python evaluate.py`, 가상 데이터 5세트 × 스푸핑 8건)

| 대량 주문 기준(중앙값 배수) | 정밀도 | 재현율 | F1 |
|---|---|---|---|
| 3배 | 0.625 | 1.0 | 0.769 |
| 5배 | 0.678 | 1.0 | 0.808 |
| **10배 (채택)** | **0.909** | **1.0** | **0.952** |
| 20배 | 1.0 | 0.9 | 0.947 |

기준을 낮추면 정상 대량 주문까지 잡아 오탐이 늘고, 높이면 작은 스푸핑을 놓칩니다. F1이 가장 높은 10배를 기본값으로 썼습니다.

## 구조

```
server.py       MCP 서버. 도구를 등록하고 오류를 Claude가 읽을 수 있는 메시지로 변환
stock.py        시세 조회와 지표 계산 (MCP와 분리해 네트워크 없이 테스트 가능)
call_log.py     모든 도구 호출을 logs/tool_calls.jsonl에 기록 (입력, 소요 시간, 성공 여부, 오류)
log_report.py   호출 로그를 도구별 호출 수·오류율·평균 응답 시간으로 집계
simulator.py    가상 틱·호가 이벤트 생성 (스푸핑 패턴 포함) → vault/
microstructure.py  vault 원본으로 미시구조 지표와 스푸핑 의심 구간 계산
policy.py       원본 반출 차단 규칙
tiers.py        EDU/Enterprise 등급별 도구 권한과 데이터 지연
evaluate.py     스푸핑 탐지 정밀도·재현율 평가
tests/          지표 계산, 로그 기록, 반출 정책, 탐지 정확도 테스트
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
.venv\Scripts\python simulator.py
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
- 학습용으로 실제 사용에는 쓰일 수 없습니다
