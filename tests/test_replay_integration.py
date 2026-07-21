from datetime import date
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from simcore.config import Config
from simcore.replay import DataBundle, FlowEvent, run_replay

def make_ohlcv(closes, idx):
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({
        "open": c.shift(1).fillna(c.iloc[0]),
        "high": c * 1.005, "low": c * 0.995,
        "close": c, "volume": np.full(len(c), 10_000.0),
    }, index=idx)

def make_bundle():
    idx = pd.bdate_range("2024-10-01", periods=160)
    # UPUP: 120일 상승 후 하루 -20% 폭락 → 매수 후 손절 시나리오
    # (-20%: 상승 중 익절/재매수로 평단이 갱신되어도 확실히 -7% 손절선을 뚫는 크기)
    closes = list(100 * (1.005 ** np.arange(120)))
    crash = closes[-1] * 0.80
    closes += [crash] * 40
    kr = {"UPUP": make_ohlcv(closes, idx)}
    fx = pd.Series(1300.0, index=idx)
    return DataBundle(kr=kr, us={}, fx=fx), idx

CFG = replace(Config(), rules=replace(Config().rules, buy_score_min=1))

def test_buys_then_stops_out_deterministically():
    bundle, idx = make_bundle()
    r1 = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    r2 = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    trades = r1.trades[r1.trades.character == "국내형"]
    assert (trades.side == "BUY").sum() >= 1
    # v2: 매수 후 상승 지속 시 트레일링 티어가 먼저 잠기므로 (-7% 원본 손절선이 아니라)
    # TRAILING_STOP 으로 청산될 수 있다. 두 사유 모두 "폭락에 의한 강제 청산"이라는
    # 테스트 의도(결정론적 강제매도)를 충족한다.
    assert {"STOP_LOSS", "TRAILING_STOP"} & set(trades.reason)
    pd.testing.assert_frame_equal(r1.trades, r2.trades)  # 결정론

def test_trades_dataframe_carries_decision_type_and_trigger_rule():
    """trades DataFrame에 decision_type/trigger_rule 컬럼이 있어야 하고,
    강제청산(STOP_LOSS/TRAILING_STOP) 행은 decision_type=="FORCED_SELL" 이며
    trigger_rule 이 R7/R10 이어야 한다(engine.check_stops 배선, Task 1·2)."""
    bundle, idx = make_bundle()
    r = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    assert {"decision_type", "trigger_rule"} <= set(r.trades.columns)
    forced = r.trades[r.trades.reason.isin(["STOP_LOSS", "TRAILING_STOP"])]
    assert not forced.empty
    assert (forced["decision_type"] == "FORCED_SELL").all()
    assert set(forced["trigger_rule"]) <= {"R7", "R10"}

def test_equity_curve_continuous_and_invariant():
    bundle, idx = make_bundle()
    r = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    eq = r.equity["국내형"]
    assert eq.notna().all()
    assert (eq > 0).all()

def test_withdrawal_flow_with_liquidation():
    bundle, idx = make_bundle()
    # 매수 체결(약 62번째 세션 이후)이 확실히 끝난 날짜에 거액 출금 + UPUP 청산 지정
    wd_date = idx[115].date()
    flows = [FlowEvent(wd_date, "국내형", -95_000_000, ("UPUP",))]
    r = run_replay(CFG, bundle, idx[70].date(), idx[-1].date(), flows=flows)
    tr = r.trades[(r.trades.character == "국내형") & (r.trades.reason == "USER_WITHDRAWAL")]
    assert len(tr) == 1
    assert r.flows_by_char["국내형"].sum() == pytest.approx(-95_000_000)

def test_snapshot_carries_scores(tmp_path):
    # 상승 추세 합성 데이터로 리플레이 → 최소 하나의 매수(점수 게이트 통과) 발생
    import numpy as np, pandas as pd
    from datetime import date
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay

    idx = pd.date_range("2025-06-01", periods=200, freq="B")
    up = np.linspace(100, 400, 200)
    df = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2,
                       "close": up, "volume": np.linspace(1000, 5000, 200)}, index=idx)
    bundle = DataBundle(kr={"AAA": df}, us={},
                        fx=pd.Series(1300.0, index=idx))
    res = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    # 거래가 발생했고 매수 거래에 green_score 기록
    buys = res.trades[res.trades.side == "BUY"] if not res.trades.empty else res.trades
    assert not buys.empty
    assert (buys["green_score"] >= 18).all()

def test_replay_result_exposes_final_state():
    import numpy as np, pandas as pd
    from datetime import date
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    idx = pd.date_range("2025-06-01", periods=200, freq="B")
    up = np.linspace(100, 400, 200)
    df = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2,
                       "close": up, "volume": np.linspace(1000, 5000, 200)}, index=idx)
    res = run_replay(Config(), DataBundle(kr={"AAA": df}, us={},
                     fx=pd.Series(1300.0, index=idx)), date(2025, 9, 1), date(2026, 2, 1))
    assert set(res.positions_by_char) == {"국내형", "해외형", "범용형"}
    assert isinstance(res.cash_by_char["국내형"], dict)
    assert "AAA" in res.last_close
    # 보유가 있으면 트레일링 상태 필드 포함
    for plist in res.positions_by_char.values():
        for p in plist:
            assert {"symbol","market","quantity","avg_price","peak_price","locked_stop_pct"} <= set(p)

def test_bear_guard_suppresses_buys_in_index_downtrend():
    import numpy as np, pandas as pd
    from datetime import date
    from dataclasses import replace
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 400, 220)
    df = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2, "close": up,
                       "volume": np.linspace(1e3, 5e3, 220)}, index=idx)
    # 종목은 상승, 그러나 지수는 하락 추세 → 가드 on이면 매수 억제
    down_index = pd.Series(np.linspace(400, 100, 220), index=idx)
    bundle = DataBundle(kr={"AAA": df}, us={}, fx=pd.Series(1300.0, index=idx),
                        kr_index=down_index)
    cfg_on = replace(Config(), rules=replace(Config().rules,
                     bear_guard_characters=frozenset({"국내형", "해외형", "범용형"})))
    res_on = run_replay(cfg_on, bundle, date(2025, 9, 1), date(2026, 2, 1))
    res_off = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    n_on = 0 if res_on.trades.empty else (res_on.trades.side == "BUY").sum()
    n_off = 0 if res_off.trades.empty else (res_off.trades.side == "BUY").sum()
    assert n_on < n_off        # 가드가 하락장 매수를 억제

def test_summary_benchmark_delta_present_with_kr_index():
    bundle, idx = make_bundle()
    kr_index = pd.Series(np.linspace(100, 130, len(idx)), index=idx)  # 상승 지수
    bundle = replace(bundle, kr_index=kr_index)
    r = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    s = r.summary["국내형"]
    assert s["benchmark_return"] is not None
    assert s["benchmark_delta"] is not None
    assert s["benchmark_delta"] == pytest.approx(s["twr"] - s["benchmark_return"])
    assert s["benchmark_name"] == "KOSPI200"

def test_summary_benchmark_delta_none_without_index():
    bundle, idx = make_bundle()  # kr_index=None (기본값)
    r = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    s = r.summary["국내형"]
    assert s["benchmark_return"] is None
    assert s["benchmark_delta"] is None
    assert s["benchmark_name"] == ""

def test_bear_guard_v2_universal_buys_when_only_one_market_bearish():
    import numpy as np, pandas as pd
    from datetime import date
    from dataclasses import replace
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 400, 220)
    mk = lambda: pd.DataFrame({"open": up, "high": up + 2, "low": up - 2, "close": up,
                               "volume": np.linspace(1e3, 5e3, 220)}, index=idx)
    bundle = DataBundle(kr={"AAA": mk()}, us={"BBB": mk()}, fx=pd.Series(1300.0, index=idx),
                        kr_index=pd.Series(np.linspace(400, 100, 220), index=idx),   # KR 하락
                        us_index=pd.Series(np.linspace(100, 400, 220), index=idx))   # US 상승
    cfg_on = replace(Config(), rules=replace(Config().rules,
                     bear_guard_characters=frozenset({"국내형", "해외형", "범용형"})))
    res = run_replay(cfg_on, bundle, date(2025, 9, 1), date(2026, 2, 1))
    buys = res.trades[(res.trades.side == "BUY") & (res.trades.character == "범용형")] if not res.trades.empty else res.trades
    assert len(buys) > 0        # 한쪽만 하락 → 범용형 매수 허용(v1이면 KR 매수 전면 차단이었음)

def test_summary_benchmark_universal_averages_both_markets():
    import numpy as np, pandas as pd
    from datetime import date
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    from simcore import metrics
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 400, 220)
    mk = lambda: pd.DataFrame({"open": up, "high": up + 2, "low": up - 2, "close": up,
                               "volume": np.linspace(1e3, 5e3, 220)}, index=idx)
    kr_index = pd.Series(np.linspace(100, 130, 220), index=idx)
    us_index = pd.Series(np.linspace(200, 260, 220), index=idx)
    bundle = DataBundle(kr={"AAA": mk()}, us={"BBB": mk()}, fx=pd.Series(1300.0, index=idx),
                        kr_index=kr_index, us_index=us_index)
    start, end = date(2025, 9, 1), date(2026, 2, 1)
    res = run_replay(Config(), bundle, start, end)
    s = res.summary["범용형"]
    kr_r = metrics.benchmark_return(kr_index, start, end)
    us_r = metrics.benchmark_return(us_index, start, end)
    assert s["benchmark_return"] == pytest.approx((kr_r + us_r) / 2)
    assert s["benchmark_delta"] == pytest.approx(s["twr"] - s["benchmark_return"])
    assert s["benchmark_name"] == "혼합"
    # 단일시장 캐릭터: 해외형=US 지수(S&P500)
    su = res.summary["해외형"]
    assert su["benchmark_return"] == pytest.approx(us_r)
    assert su["benchmark_name"] == "S&P500"

def test_summary_benchmark_universal_uses_single_index_when_only_one_available():
    import numpy as np, pandas as pd
    from datetime import date
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    from simcore import metrics
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 400, 220)
    mk = lambda: pd.DataFrame({"open": up, "high": up + 2, "low": up - 2, "close": up,
                               "volume": np.linspace(1e3, 5e3, 220)}, index=idx)
    kr_index = pd.Series(np.linspace(100, 130, 220), index=idx)
    bundle = DataBundle(kr={"AAA": mk()}, us={"BBB": mk()}, fx=pd.Series(1300.0, index=idx),
                        kr_index=kr_index, us_index=None)
    start, end = date(2025, 9, 1), date(2026, 2, 1)
    res = run_replay(Config(), bundle, start, end)
    s = res.summary["범용형"]
    kr_r = metrics.benchmark_return(kr_index, start, end)
    assert s["benchmark_return"] == pytest.approx(kr_r)
    assert s["benchmark_delta"] == pytest.approx(s["twr"] - s["benchmark_return"])
    assert s["benchmark_name"] == "KOSPI200"

def test_replay_signal_status_holds_position_with_stop_px_and_candidates():
    """Task 2: ReplayResult.signal_status 는 마지막 거래일의 후보(engine.last_candidates)
    + 보유 상태(캐릭터별 보유 종목의 stop_px=avg*(1+locked_stop_pct), trail_px, close)를
    담아야 한다."""
    import numpy as np, pandas as pd
    from datetime import date
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    idx = pd.date_range("2025-06-01", periods=200, freq="B")
    up = np.linspace(100, 400, 200)
    df = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2,
                       "close": up, "volume": np.linspace(1000, 5000, 200)}, index=idx)
    cfg = Config()
    res = run_replay(cfg, DataBundle(kr={"AAA": df}, us={},
                     fx=pd.Series(1300.0, index=idx)), date(2025, 9, 1), date(2026, 2, 1))

    assert res.signal_status  # 비어있지 않음
    last_day = res.equity.index[-1].date()

    held_rows = [r for r in res.signal_status if r["kind"] == "보유"]
    assert held_rows
    kr_pos = next(p for p in res.positions_by_char["국내형"] if p["symbol"] == "AAA")
    row = next(r for r in held_rows
               if r["character"] == "국내형" and r["symbol"] == "AAA")
    assert row["date"] == last_day
    assert row["close"] == pytest.approx(res.last_close["AAA"])
    expected_stop = kr_pos["avg_price"] * (1 + kr_pos["locked_stop_pct"])
    assert row["stop_px"] == pytest.approx(expected_stop)
    peak_gain = kr_pos["peak_price"] / kr_pos["avg_price"] - 1.0
    if peak_gain >= cfg.rules.trailing_top:
        expected_trail = kr_pos["peak_price"] * (1 - cfg.rules.trail_pct)
        assert row["trail_px"] == pytest.approx(expected_trail)
    else:
        assert row["trail_px"] is None

    cand_rows = [r for r in res.signal_status if r["kind"] == "후보"]
    assert cand_rows  # engine.last_candidates 기반(보유중 차단 포함)
    assert all(r["date"] == last_day for r in cand_rows)

def test_replay_signal_status_carries_forward_red_score_when_last_day_snapshot_missing():
    """#7: 보유 종목이 마지막 거래일의 universe 프레임에 없으면(랭킹 이탈 등) red_score
    를 0 으로 리셋하지 않고, 그 종목이 마지막으로 스냅샷을 가졌던 날의 red_score 를
    승계해야 한다(orchestrator._prior_held_red_score 와 동일 원칙, replay 쪽 회귀 재현)."""
    import numpy as np, pandas as pd
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    from simcore import signals as sigmod

    idx = pd.bdate_range("2024-10-01", periods=200)
    up = np.linspace(100, 400, 200)
    vol_down = np.linspace(5000, 1000, 200)   # 상승가 + 하락거래량 → R24(거래량 감소중 상승) 지속 발화
    bbb = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2,
                        "close": up, "volume": vol_down}, index=idx)
    aaa = bbb.iloc[:190]                      # AAA 는 190일치만 존재 → 마지막 10일은 유니버스 이탈
    cfg = Config()
    bundle = DataBundle(kr={"AAA": aaa, "BBB": bbb}, us={}, fx=pd.Series(1300.0, index=idx))
    res = run_replay(cfg, bundle, idx[100].date(), idx[-1].date())

    # AAA 가 여전히 보유 중이어야 시나리오가 유효 (마지막 날 스냅 누락 + 보유 지속)
    assert any(p["symbol"] == "AAA" for p in res.positions_by_char["국내형"])

    # AAA 가 마지막으로 프레임에 있었던 날(idx[189])의 red_score 를 독립적으로 재계산
    frame = sigmod.evaluate_frame(aaa, cfg.signals)
    last_aaa_ts = aaa.index[-1]
    green, red = sigmod.fired_at(frame, last_aaa_ts)
    _, expected_red_score, _ = sigmod.snapshot_scores(green, red, cfg.scores)
    assert expected_red_score != 0  # 시나리오 전제: 이탈 직전 red_score 가 0 이 아님

    held_row = next(r for r in res.signal_status
                    if r["kind"] == "보유" and r["character"] == "국내형" and r["symbol"] == "AAA")
    assert held_row["red_score"] == expected_red_score  # 0 으로 리셋되지 않고 직전값 승계
