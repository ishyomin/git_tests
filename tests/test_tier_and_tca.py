"""이용 등급별 권한, 지연 제공, TCA 추정 테스트."""

from datetime import timedelta

import pytest

import microstructure
import policy
import simulator
import tiers


@pytest.fixture(scope="module", autouse=True)
def vault(tmp_path_factory):
    path = tmp_path_factory.mktemp("vault")
    df, _ = simulator.simulate(seed=7)
    df.to_csv(path / "DEMO01_events.csv", index=False)
    original = microstructure.VAULT
    microstructure.VAULT = path
    microstructure._load.cache_clear()
    yield
    microstructure.VAULT = original
    microstructure._load.cache_clear()


@pytest.fixture
def edu(monkeypatch):
    monkeypatch.setenv("STOCK_MCP_TIER", "edu")


# ---------------------------------------------------------------- 등급

def test_default_tier_is_enterprise(monkeypatch):
    monkeypatch.delenv("STOCK_MCP_TIER", raising=False)
    assert tiers.current() == "enterprise"
    tiers.check_tool("surveillance_scan")  # 예외 없음


def test_edu_cannot_use_enterprise_tools(edu):
    for tool in ("surveillance_scan", "tca_estimate"):
        with pytest.raises(policy.PolicyError):
            tiers.check_tool(tool)
    tiers.check_tool("market_microstructure")  # 기본 지표는 허용


def test_unknown_tier_is_rejected(monkeypatch):
    monkeypatch.setenv("STOCK_MCP_TIER", "vip")
    with pytest.raises(policy.PolicyError):
        tiers.current()


def test_edu_gets_20_minute_delay(edu):
    end = microstructure.session_end("DEMO01")  # 11:00 무렵
    limited = tiers.clamp_end(None, end)
    assert limited == (end - timedelta(minutes=20)).strftime("%H:%M")
    assert tiers.clamp_end("09:30", end) == "09:30"  # 지연 한도 이전 요청은 그대로


def test_enterprise_has_no_delay(monkeypatch):
    monkeypatch.setenv("STOCK_MCP_TIER", "enterprise")
    assert tiers.clamp_end(None, microstructure.session_end("DEMO01")) is None


# ---------------------------------------------------------------- TCA

def test_tca_small_order_costs_only_half_spread():
    r = microstructure.tca_estimate("DEMO01", "buy", 1, "10:00")
    assert r["levels_consumed"] == 1
    assert r["impact_bps"] == 0
    assert r["slippage_bps"] == r["spread_cost_bps"] > 0


def test_tca_bigger_order_costs_more():
    small = microstructure.tca_estimate("DEMO01", "sell", 10, "10:00")
    big = microstructure.tca_estimate("DEMO01", "sell", 5000, "10:00")
    assert big["levels_consumed"] > small["levels_consumed"]
    assert big["slippage_bps"] > small["slippage_bps"]


def test_tca_output_has_no_order_info():
    policy.enforce_output(microstructure.tca_estimate("DEMO01", "buy", 100, "10:00"))


@pytest.mark.parametrize("args", [("hold", 10, "10:00"), ("buy", 0, "10:00"), ("buy", 10, "08:00")])
def test_tca_rejects_bad_input(args):
    with pytest.raises(ValueError):
        microstructure.tca_estimate("DEMO01", *args)
