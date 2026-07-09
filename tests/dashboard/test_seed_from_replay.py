"""리플레이 결과 DB 시딩 — 총자산·자산곡선 정합성 검증(순수 함수, 네트워크 없음)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import date

from simcore.config import Config
from simcore.replay import DataBundle, run_replay
from dashboard.scripts.seed_from_replay import seed_replay_result_into_db
from dashboard.backend import summary, queries
from simcore.live import db


def _bundle():
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 500, 220)
    df = pd.DataFrame({"open": up, "high": up + 3, "low": up - 3, "close": up,
                       "volume": np.linspace(1e6, 5e6, 220)}, index=idx)
    return DataBundle(kr={"005930": df}, us={}, fx=pd.Series(1300.0, index=idx))


def test_seed_makes_card_total_match_equity_last():
    bundle = _bundle()
    result = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    engine = db.make_engine("sqlite://")   # in-memory
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    seed_replay_result_into_db(result, bundle, sf, fx_rate=1300.0)

    checked_any = False
    for name in ["국내형", "해외형", "범용형"]:
        eq = queries.equity_series(sf, name)
        if not eq:
            continue
        lp = queries.last_prices(sf, queries.positions(sf, name))
        card = summary.card_summary(sf, name, 1300.0, lp)
        assert abs(card.total_asset_krw - eq[-1][1]) < 1.0   # 동일 스냅샷 → 정합
        checked_any = True
    assert checked_any


def test_seed_requires_force_flag_when_run_as_cli(monkeypatch):
    """--force 없이 CLI 실행하면 즉시 종료(가드)한다."""
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["seed_from_replay.py"])
    try:
        runpy.run_path("dashboard/scripts/seed_from_replay.py", run_name="__main__")
        assert False, "SystemExit 이 발생해야 한다"
    except SystemExit as exc:
        assert exc.code  # 0 이 아닌/문자열 메시지
