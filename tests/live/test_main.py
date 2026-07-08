import os

from tests.live.conftest import needs_db
from simcore.live.settings import LiveSettings
from simcore.live.__main__ import build_app


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
