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

CFG = replace(Config(), rules=replace(Config().rules, buy_threshold=3))

def test_buys_then_stops_out_deterministically():
    bundle, idx = make_bundle()
    r1 = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    r2 = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    trades = r1.trades[r1.trades.character == "국내형"]
    assert (trades.side == "BUY").sum() >= 1
    assert "STOP_LOSS" in set(trades.reason)
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
