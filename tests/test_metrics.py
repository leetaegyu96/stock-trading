import pandas as pd
import pytest
from simcore.metrics import time_weighted_return, max_drawdown, simple_pnl_krw

IDX = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])

def test_twr_without_flows_equals_simple_return():
    eq = pd.Series([100.0, 110.0, 121.0], index=IDX)
    assert time_weighted_return(eq) == pytest.approx(0.21)

def test_twr_ignores_deposit_distortion():
    # 실력은 0% 인데 둘째 날 100 입금 → 단순 수익률은 +100%, TWR 은 0% 여야 함
    eq = pd.Series([100.0, 200.0, 200.0], index=IDX)
    flows = pd.Series([0.0, 100.0, 0.0], index=IDX)
    assert time_weighted_return(eq, flows) == pytest.approx(0.0)

def test_twr_ignores_withdrawal_distortion():
    eq = pd.Series([100.0, 50.0, 50.0], index=IDX)
    flows = pd.Series([0.0, -50.0, 0.0], index=IDX)
    assert time_weighted_return(eq, flows) == pytest.approx(0.0)

def test_max_drawdown():
    eq = pd.Series([100.0, 120.0, 90.0, 110.0],
                   index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]))
    assert max_drawdown(eq) == pytest.approx(-0.25)  # 120 → 90

def test_simple_pnl_subtracts_net_flows():
    eq = pd.Series([100.0, 200.0, 210.0], index=IDX)
    flows = pd.Series([0.0, 100.0, 0.0], index=IDX)
    assert simple_pnl_krw(eq, flows) == pytest.approx(10.0)

def test_twr_skips_period_with_nonpositive_base():
    # 둘째 날 전액 출금(자산 0) → 그 구간과 이후 재입금 구간은 배율 1로 건너뜀
    idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"])
    eq = pd.Series([100.0, 0.0, 100.0, 110.0], index=idx)
    flows = pd.Series([0.0, -100.0, 100.0, 0.0], index=idx)
    # day2: base=100-100=0 → skip, day3: base=0+100=100, r=1.0, day4: r=1.1
    assert time_weighted_return(eq, flows) == pytest.approx(0.10)

def test_twr_ignores_flow_dates_missing_from_equity():
    idx = pd.to_datetime(["2025-01-02", "2025-01-03"])
    eq = pd.Series([100.0, 110.0], index=idx)
    flows = pd.Series([50.0], index=pd.to_datetime(["2025-02-01"]))  # equity 에 없는 날짜
    assert time_weighted_return(eq, flows) == pytest.approx(0.10)
