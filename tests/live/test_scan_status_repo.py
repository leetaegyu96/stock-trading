import os
from datetime import datetime
from tests.live.conftest import needs_db
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory


@needs_db
def test_record_scan_upserts_latest_per_market(session):
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    ts1 = datetime(2026, 7, 21, 13, 40, 0)
    repo.record_scan("KR", ts=ts1, universe_size=60, evaluated=58, failed=2,
                     gate_pass=3, buys=1, sells=0, scan_minutes=10)
    rows = repo.scan_status()
    assert len(rows) == 1
    r = rows[0]
    assert r["market"] == "KR"
    assert r["universe_size"] == 60 and r["evaluated"] == 58 and r["failed"] == 2
    assert r["gate_pass"] == 3 and r["buys"] == 1 and r["sells"] == 0
    assert r["scan_minutes"] == 10

    # 같은 시장 재기록 → 교체(시장별 최신 1행 유지)
    ts2 = datetime(2026, 7, 21, 13, 50, 0)
    repo.record_scan("KR", ts=ts2, universe_size=60, evaluated=60, failed=0,
                     gate_pass=5, buys=0, sells=2, scan_minutes=10)
    rows = repo.scan_status()
    assert len(rows) == 1
    assert rows[0]["evaluated"] == 60 and rows[0]["sells"] == 2

    # 다른 시장 추가 → 2행(시장별 독립)
    repo.record_scan("US", ts=ts2, universe_size=30, evaluated=30, failed=0,
                     gate_pass=1, buys=0, sells=0, scan_minutes=10)
    rows = repo.scan_status()
    assert {r["market"] for r in rows} == {"KR", "US"}
