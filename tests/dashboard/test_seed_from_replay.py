"""리플레이 결과 DB 시딩 — 총자산·자산곡선 정합성 검증(순수 함수, 네트워크 없음)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import date

from simcore.config import Config
from simcore.replay import DataBundle, run_replay
from dashboard.scripts.seed_from_replay import seed_replay_result_into_db
from dashboard.backend import summary, queries
from dashboard.backend.constants import FALLBACK_FX_RATE
from simcore.live import db


def _bundle():
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 500, 220)
    df = pd.DataFrame({"open": up, "high": up + 3, "low": up - 3, "close": up,
                       "volume": np.linspace(1e6, 5e6, 220)}, index=idx)
    return DataBundle(kr={"005930": df}, us={}, fx=pd.Series(1300.0, index=idx))


def _bundle_with_us_and_drifting_fx():
    """KR + US 종목을 모두 포함하고, fx 가 리플레이 구간 동안 1300→1400 으로 계속
    변하는(상승 추세) 합성 데이터. 해외형·범용형이 실제로 USD(AAPL) 포지션을 들고
    구간을 마치도록 만들어, Fix 1(마지막 EquityPoint 를 조회 fx 로 재평가)이 없으면
    깨지는 케이스를 재현한다."""
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up_kr = np.linspace(100, 500, 220)
    df_kr = pd.DataFrame({"open": up_kr, "high": up_kr + 3, "low": up_kr - 3,
                          "close": up_kr, "volume": np.linspace(1e6, 5e6, 220)}, index=idx)
    up_us = np.linspace(50, 250, 220)
    df_us = pd.DataFrame({"open": up_us, "high": up_us + 3, "low": up_us - 3,
                          "close": up_us, "volume": np.linspace(1e6, 5e6, 220)}, index=idx)
    fx = pd.Series(np.linspace(1300.0, 1400.0, 220), index=idx)  # 상수가 아님
    return DataBundle(kr={"005930": df_kr}, us={"AAPL": df_us}, fx=fx)


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


def test_seed_writes_benchmark_row_per_character():
    """seed_from_replay 가 result.summary 의 benchmark_return/name 을 BenchmarkRow 로
    적재해, 대시보드가 요청 시점에 네트워크 없이 벤치마크를 읽을 수 있어야 한다."""
    bundle = _bundle()
    result = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    seed_replay_result_into_db(result, bundle, sf, fx_rate=1300.0)

    checked_any = False
    for name in result.summary:
        row = queries.benchmark(sf, name)
        assert row is not None, f"{name} 벤치마크 row 가 시딩되어야 함"
        assert row["benchmark_return"] == result.summary[name]["benchmark_return"]
        assert row["benchmark_name"] == result.summary[name]["benchmark_name"]
        checked_any = True
    assert checked_any


def test_seed_writes_nonnull_benchmark_return_with_indices_and_guard_off():
    """지수 로딩은 하락장 가드(bear_guard_characters) 스위치와 분리되어야 한다.
    가드가 꺼져 있어도(Config() 기본값 = 빈 set) bundle 에 kr_index 가 있으면
    summary.benchmark_return 이 계산되고, 시딩된 BenchmarkRow 에도 그 값이 그대로
    반영되어야 한다(P0-3: 전략 vs 벤치마크가 항상 나와야 함)."""
    bundle = _bundle_with_us_and_drifting_fx()  # KR+US 종목 모두 포함 → 세 캐릭터 모두 검증 가능
    idx = bundle.kr["005930"].index
    kr_index = pd.Series(np.linspace(2000, 2400, len(idx)), index=idx)  # 상승 지수
    us_index = pd.Series(np.linspace(4000, 4800, len(idx)), index=idx)  # 상승 지수
    bundle = DataBundle(kr=bundle.kr, us=bundle.us, fx=bundle.fx,
                        kr_index=kr_index, us_index=us_index)

    cfg = Config()
    assert not cfg.rules.bear_guard_characters  # 가드 off 임을 확인

    result = run_replay(cfg, bundle, date(2025, 9, 1), date(2026, 2, 1))
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    seed_replay_result_into_db(result, bundle, sf, fx_rate=1300.0)

    checked_any = False
    for name in result.summary:
        assert result.summary[name]["benchmark_return"] is not None
        row = queries.benchmark(sf, name)
        assert row is not None
        assert row["benchmark_return"] is not None
        assert row["benchmark_return"] == result.summary[name]["benchmark_return"]
        checked_any = True
    assert checked_any


def test_seed_matches_exactly_with_drifting_fx_for_usd_holders():
    """fx 가 상수가 아닐 때(리플레이 마지막날 fx != 조회 fx_rate)도 USD 를 보유하는
    해외형/범용형까지 포함해 총자산 정합이 정확히 성립해야 한다(Fix 1 없이는 실패)."""
    bundle = _bundle_with_us_and_drifting_fx()
    result = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    query_fx_rate = 1300.0  # 리플레이 마지막날 fx(≈1400)와 다른 값으로 조회
    seed_replay_result_into_db(result, bundle, sf, fx_rate=query_fx_rate)

    checked_usd_holder = False
    for name in ["국내형", "해외형", "범용형"]:
        eq = queries.equity_series(sf, name)
        assert eq, f"{name} equity 가 비어 있음"
        positions = queries.positions(sf, name)
        lp = queries.last_prices(sf, positions)
        card = summary.card_summary(sf, name, query_fx_rate, lp)
        assert abs(card.total_asset_krw - eq[-1][1]) < 1.0
        if any(p["market"] == "US" for p in positions):
            checked_usd_holder = True
    assert checked_usd_holder  # 이 케이스가 실제로 USD 보유 캐릭터를 검증했는지 확인


def test_seed_preserves_real_today_return_for_usd_holders():
    """Fix 3 회귀 가드: 마지막 EquityPoint 만 조회 fx_rate 로 덮어쓰면(예전 방식),
    직전 점은 리플레이 당시의 fx(드리프트 중)로 계산된 값이라 오늘 수익률이 fx 차이만큼
    가짜로 왜곡된다(과거 실제로 해외형/범용형에서 약 -14% 발생). 전체 곡선을 상수
    비율로 스케일링하면 총자산 정합(마지막 점)은 그대로 유지하면서, 오늘 수익률은
    리플레이가 계산한 실제 마지막 날 수익률(col.iloc[-1]/col.iloc[-2]-1)과 정확히
    일치해야 한다."""
    bundle = _bundle_with_us_and_drifting_fx()
    result = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    query_fx_rate = 1300.0  # 리플레이 마지막날 fx(≈1400)와 다른 값으로 조회
    seed_replay_result_into_db(result, bundle, sf, fx_rate=query_fx_rate)

    checked_usd_holder = False
    for name in ["국내형", "해외형", "범용형"]:
        positions = queries.positions(sf, name)
        if not any(p["market"] == "US" for p in positions):
            continue  # KRW 만 보유한 캐릭터는 fx 재평가로 왜곡될 여지가 없음

        col = result.equity[name]
        expected_today_pct = float(col.iloc[-1] / col.iloc[-2] - 1.0)

        lp = queries.last_prices(sf, positions)
        card = summary.card_summary(sf, name, query_fx_rate, lp)

        assert abs(card.today_pnl_pct - expected_today_pct) < 1e-9
        # fx 왜곡(예전 방식)이었다면 여기서 수십 %p 벌어졌을 것 — 실제로는 작은 진짜 수익률.
        assert abs(card.today_pnl_pct) < 0.05
        checked_usd_holder = True
    assert checked_usd_holder  # 이 케이스가 실제로 USD 보유 캐릭터를 검증했는지 확인


def test_seed_persists_decision_type_and_trigger_rule():
    """Task 6: 리플레이 trades DataFrame의 decision_type/trigger_rule(Task 1·2)이
    시딩된 TradeRow에 그대로 보존되어야 한다 — 대시보드(Task 7/8)가 이 컬럼을 읽는다."""
    bundle = _bundle()
    result = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    engine = db.make_engine("sqlite://")
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    seed_replay_result_into_db(result, bundle, sf, fx_rate=1300.0)

    assert not result.trades.empty
    with sf() as s:
        rows = s.query(db.TradeRow).order_by(db.TradeRow.id).all()
        assert len(rows) == len(result.trades)
        for row, (_, exp) in zip(rows, result.trades.iterrows()):
            assert row.decision_type == exp["decision_type"]
            assert row.trigger_rule == exp["trigger_rule"]


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


def test_cli_seeds_with_shared_fallback_fx_rate(monkeypatch):
    """회귀 가드: CLI(_cli)가 seed_replay_result_into_db 에 넘기는 fx_rate 는 반드시
    dashboard.backend.constants.FALLBACK_FX_RATE(카드가 쓰는 고정값)여야 한다.
    누군가 다시 `fx_rate = float(bundle.fx.iloc[-1])`(리플레이 마지막날의 실제 환율)로
    되돌리면, 이 테스트의 bundle(fx 가 1300→1400 으로 변함)에서 즉시 실패한다."""
    import sys

    import dashboard.scripts.seed_from_replay as mod
    from simcore import data as datamod, universe

    bundle = _bundle_with_us_and_drifting_fx()  # 마지막날 fx = 1400.0 (!= FALLBACK_FX_RATE)

    monkeypatch.setattr(universe, "kospi200", lambda *a, **k: list(bundle.kr.keys()))
    monkeypatch.setattr(universe, "sp500", lambda *a, **k: list(bundle.us.keys()))
    monkeypatch.setattr(datamod, "load_kr_daily", lambda *a, **k: bundle.kr)
    monkeypatch.setattr(datamod, "load_us_daily", lambda *a, **k: bundle.us)
    monkeypatch.setattr(datamod, "load_fx", lambda *a, **k: bundle.fx)
    # 지수 로딩은 가드 스위치와 무관하게 항상 호출되므로(벤치마크 상시 계산),
    # 네트워크 호출 없이 결정적으로 동작하도록 목(mock) 처리한다.
    monkeypatch.setattr(datamod, "load_index", lambda *a, **k: None)

    captured = {}
    real_seed = mod.seed_replay_result_into_db

    def spy_seed(result, bundle_, sf, fx_rate=None, initial_capital_krw=None):
        captured["fx_rate"] = fx_rate
        return real_seed(result, bundle_, sf, fx_rate=fx_rate,
                          initial_capital_krw=initial_capital_krw)

    monkeypatch.setattr(mod, "seed_replay_result_into_db", spy_seed)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setattr(sys, "argv", [
        "seed_from_replay.py", "--force",
        "--start", "2025-09-01", "--end", "2026-02-01",
    ])

    mod._cli()

    assert abs(bundle.fx.iloc[-1] - FALLBACK_FX_RATE) > 1.0  # 이 테스트가 실제로 두 값을 구분하는지 확인
    assert captured["fx_rate"] == FALLBACK_FX_RATE
