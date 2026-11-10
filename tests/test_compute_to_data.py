"""Compute-to-Data: 반출 정책, 미시구조 지표, 스푸핑 탐지 테스트.

가상 데이터를 임시 폴더에 새로 만들어 쓰므로 vault/가 없어도 실행된다.
"""

import pytest

import microstructure
import policy
import simulator


@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    path = tmp_path_factory.mktemp("vault")
    df, labels = simulator.simulate(seed=7)
    df.to_csv(path / "DEMO01_events.csv", index=False)
    original = microstructure.VAULT
    microstructure.VAULT = path
    microstructure._load.cache_clear()
    yield labels
    microstructure.VAULT = original
    microstructure._load.cache_clear()


# ---------------------------------------------------------------- 반출 정책

def test_window_shorter_than_minimum_is_rejected():
    with pytest.raises(policy.PolicyError):
        policy.check_window(30)


def test_order_id_cannot_leave():
    with pytest.raises(policy.PolicyError):
        policy.enforce_output({"rows": [{"order_id": 1, "qty": 10}]})


def test_too_many_rows_cannot_leave():
    with pytest.raises(policy.PolicyError):
        policy.enforce_output({"rows": [{}] * (policy.MAX_ROWS + 1)})


# ---------------------------------------------------------------- 파생 지표

def test_microstructure_returns_only_aggregates(vault):
    result = microstructure.market_microstructure("DEMO01", "09:00", "09:30", 60)
    policy.enforce_output(result)
    assert len(result["rows"]) == 30
    row = next(r for r in result["rows"] if not r.get("suppressed"))
    assert -1 <= row["obi"] <= 1
    assert row["spread_ticks"] >= 1
    assert row["messages"] >= policy.MIN_EVENTS


def test_sparse_window_is_suppressed(vault):
    # 10분 단위 첫 구간을 1분 단위로 쪼개도, 이벤트가 적은 구간은 값이 숨겨져야 한다
    result = microstructure.market_microstructure("DEMO01", None, None, 60)
    for row in result["rows"]:
        if row["messages"] < policy.MIN_EVENTS:
            assert row.get("suppressed") is True
            assert "obi" not in row


def test_bad_time_format(vault):
    with pytest.raises(ValueError):
        microstructure.market_microstructure("DEMO01", "9시", None, 60)


def test_unknown_dataset(vault):
    with pytest.raises(ValueError):
        microstructure.market_microstructure("NOPE", None, None, 60)


# ---------------------------------------------------------------- 스푸핑 탐지

def test_surveillance_finds_all_injected_spoofs(vault):
    alerts = microstructure.surveillance_scan("DEMO01", None, None)["alerts"]
    policy.enforce_output(alerts)
    found = {(a["start"][:5], a["side"]) for a in alerts}
    expected = {(l["start"][11:16], l["side"]) for l in vault}
    assert expected <= found  # 놓친 스푸핑 없음
    # 정상 대량 주문 때문에 오탐이 조금 생길 수 있지만, 탐지의 대부분은 진짜여야 한다
    assert len(expected) / len(alerts) >= 0.8
