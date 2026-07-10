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

def test_risk_metrics_basic():
    import numpy as np, pandas as pd
    from simcore.metrics import risk_metrics
    idx = pd.date_range("2025-01-01", periods=252, freq="B")
    eq = pd.Series(np.linspace(100, 130, 252), index=idx)   # 우상향
    trades = pd.DataFrame({"side": ["SELL","SELL","SELL"], "realized_pnl": [10.0, -4.0, 6.0]})
    m = risk_metrics(eq, trades)
    assert m["cagr"] > 0 and m["calmar"] > 0
    assert m["profit_factor"] == pytest.approx(16.0/4.0)         # 이익합16/손실합4
    assert m["win_loss_ratio"] == pytest.approx((16/2)/4.0)      # 평균이익8/평균손실4
    assert m["max_consecutive_losses"] == 1
    assert m["expectancy"] == pytest.approx((10-4+6)/3)

def test_risk_metrics_empty_and_all_loss():
    import pandas as pd
    from simcore.metrics import risk_metrics
    eq = pd.Series([100.0, 90.0], index=pd.date_range("2025-01-01", periods=2))
    m = risk_metrics(eq, pd.DataFrame({"side":["SELL"], "realized_pnl":[-5.0]}))
    assert m["profit_factor"] == 0.0 and m["avg_win"] == 0.0     # 이익 없음
    m2 = risk_metrics(eq, None)                                   # 거래정보 없음
    assert m2["profit_factor"] == 0.0 and m2["expectancy"] == 0.0
