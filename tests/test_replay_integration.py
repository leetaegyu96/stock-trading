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
