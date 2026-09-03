import os
from dataclasses import dataclass

from tests.live.conftest import needs_db
from simcore.live.settings import LiveSettings
from simcore.live.__main__ import build_app, _config_from_settings


@needs_db
def test_build_app_wires_components():
    s = LiveSettings(kis_app_key="AK", kis_app_secret="SK",
                     database_url=os.environ["TEST_DATABASE_URL"], kis_env="real")
    eng, kis, repo, orch = build_app(s)
    assert set(eng.states) == {"국내형", "해외형", "범용형"}
    assert orch.engine is eng
    assert orch.repo is repo and orch.kis is kis


@needs_db
def test_deposit_withdraw_enqueue_flow():
    """CLI 진입점이 쓰는 repo.enqueue_flow 경로 — 입/출금이 큐에 부호대로 쌓인다."""
    s = LiveSettings(kis_app_key="AK", kis_app_secret="SK",
                     database_url=os.environ["TEST_DATABASE_URL"], kis_env="real")
    _, _, repo, _ = build_app(s)
    # 깨끗한 시작을 위해 기존 대기 요청 소진 여부와 무관하게 신규 2건 추가
    repo.enqueue_flow("국내형", 5_000_000.0)
    repo.enqueue_flow("해외형", -3_000_000.0, liquidate=("AAPL",))
    pend = {p.character: p for p in repo.pending_flow_requests()}
    assert pend["국내형"].amount_krw == 5_000_000.0
    assert pend["해외형"].amount_krw == -3_000_000.0
    assert list(pend["해외형"].liquidate) == ["AAPL"]


@dataclass
class _FakeSettings:
    """_config_from_settings 가 읽는 속성들."""
    intraday_enabled: bool = False
    intraday_scan_minutes: int = 10
    signal_sell_enabled: bool = True
    max_positions: int = 5
    intraday_buy_enabled: bool = True
    intraday_max_buys_per_day: int = 0
    trailing_intraday_update: bool = True


def test_config_from_settings_disabled_keeps_defaults():
    cfg = _config_from_settings(_FakeSettings(intraday_enabled=False))
    assert cfg.rules.intraday_enabled is False
    assert cfg.rules.intraday_scan_minutes == 10


def test_config_from_settings_enabled_applies_scan_minutes():
    cfg = _config_from_settings(_FakeSettings(intraday_enabled=True, intraday_scan_minutes=5))
    assert cfg.rules.intraday_enabled is True
    assert cfg.rules.intraday_scan_minutes == 5


def test_config_from_settings_defaults_keep_signal_sell_and_positions():
    cfg = _config_from_settings(_FakeSettings())
    assert cfg.rules.signal_sell_enabled is True
    assert cfg.rules.max_positions == 5


def test_config_from_settings_disables_signal_sell():
    cfg = _config_from_settings(_FakeSettings(signal_sell_enabled=False))
    assert cfg.rules.signal_sell_enabled is False
    # 강제매도 파라미터는 건드리지 않는다
    assert cfg.rules.stop_loss_pct == -0.07
    assert cfg.rules.trail_pct == 0.07


def test_config_from_settings_applies_max_positions():
    cfg = _config_from_settings(_FakeSettings(max_positions=10))
    assert cfg.rules.max_positions == 10


def test_config_from_settings_defaults_keep_intraday_brakes_off():
    cfg = _config_from_settings(_FakeSettings())
    assert cfg.rules.intraday_buy_enabled is True
    assert cfg.rules.intraday_max_buys_per_day == 0


def test_config_from_settings_applies_trailing_intraday_update():
    assert _config_from_settings(_FakeSettings()).rules.trailing_intraday_update is True
    cfg = _config_from_settings(_FakeSettings(trailing_intraday_update=False))
    assert cfg.rules.trailing_intraday_update is False
    assert cfg.rules.stop_loss_pct == -0.07      # 손절 파라미터는 불변


def test_config_from_settings_applies_intraday_brakes():
    cfg = _config_from_settings(_FakeSettings(intraday_buy_enabled=False,
                                              intraday_max_buys_per_day=2))
    assert cfg.rules.intraday_buy_enabled is False
    assert cfg.rules.intraday_max_buys_per_day == 2


@needs_db
def test_build_app_uses_single_shared_config():
    """엔진과 오케스트레이터가 서로 다른 Config 인스턴스를 갖던 잠재버그 수정 확인."""
    s = LiveSettings(kis_app_key="AK", kis_app_secret="SK",
                     database_url=os.environ["TEST_DATABASE_URL"], kis_env="real")
    eng, kis, repo, orch = build_app(s)
    assert eng.config is orch.cfg
