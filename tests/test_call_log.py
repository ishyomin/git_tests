"""호출 로그 기록과 집계를 검사하는 테스트."""

import json

import pytest

import call_log
import log_report


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    path = tmp_path / "calls.jsonl"
    monkeypatch.setattr(call_log, "LOG_PATH", path)
    return path


def test_success_is_logged(tmp_log):
    @call_log.logged
    def add(a: int, b: int) -> int:
        return a + b

    assert add(a=1, b=2) == 3
    record = json.loads(tmp_log.read_text(encoding="utf-8"))
    assert record["tool"] == "add"
    assert record["args"] == {"a": 1, "b": 2}
    assert record["status"] == "ok"
    assert "duration_ms" in record


def test_error_is_logged_and_reraised(tmp_log):
    @call_log.logged
    def fail(ticker: str):
        raise ValueError("없는 종목")

    with pytest.raises(ValueError):
        fail(ticker="XXXX")
    record = json.loads(tmp_log.read_text(encoding="utf-8"))
    assert record["status"] == "error"
    assert "없는 종목" in record["error"]


def test_report_summary():
    records = [
        {"tool": "get_price", "status": "ok", "duration_ms": 100.0},
        {"tool": "get_price", "status": "error", "duration_ms": 300.0},
        {"tool": "analyze", "status": "ok", "duration_ms": 50.0},
    ]
    summary = log_report.summarize(records)
    assert summary["get_price"] == {"calls": 2, "error_rate_pct": 50.0, "avg_ms": 200.0}
    assert summary["analyze"]["error_rate_pct"] == 0.0
