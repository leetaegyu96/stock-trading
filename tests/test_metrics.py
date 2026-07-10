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
    base = np.linspace(100, 130, 252)
    base[100:110] = base[100:110] - 8      # 실제 낙폭 구간 삽입 (mdd != 0 → calmar 일반 분기 검증)
    eq = pd.Series(base, index=idx)
    trades = pd.DataFrame({"side": ["SELL","SELL","SELL"], "realized_pnl": [10.0, -4.0, 6.0]})
    m = risk_metrics(eq, trades)
    assert m["cagr"] > 0 and m["calmar"] > 0
    assert m["profit_factor"] == pytest.approx(16.0/4.0)         # 이익합16/손실합4
    assert m["win_loss_ratio"] == pytest.approx((16/2)/4.0)      # 평균이익8/평균손실4
    assert m["max_consecutive_losses"] == 1
    assert m["expectancy"] == pytest.approx((10-4+6)/3)

def test_risk_metrics_sortino_and_recovery():
    import math
    import pandas as pd
    from simcore.metrics import risk_metrics, max_drawdown
    # 결정적(무작위 없음) 구간: 상승 → 낙폭 → 회복
    idx = pd.date_range("2025-01-01", periods=13, freq="D")
    values = [
        100, 105, 110, 115, 120,   # 2025-01-01~05: 상승, 고점 120 @ 2025-01-05
        110, 100, 90,              # 2025-01-06~08: 하락, 저점  90 @ 2025-01-08
        95, 105, 115, 121, 125,    # 2025-01-09~13: 회복, 2025-01-12(121)에서 고점 120 재돌파
    ]
    eq = pd.Series(values, index=idx)
    m = risk_metrics(eq, None)

    # 전체적으로는 순상승(100→125)이지만 하락일(day6~8)이 있어 downside_std>0 → sortino 유한/양수
    assert math.isfinite(m["sortino"]) and m["sortino"] > 0

    # calmar 는 mdd!=0(낙폭 존재) 이므로 일반 분기(cagr/|mdd|)로 계산되어야 함
    mdd = max_drawdown(eq)
    assert mdd != 0
    assert m["calmar"] == pytest.approx(m["cagr"] / abs(mdd))

    # recovery_days 손계산: 고점 120(2025-01-05) → 저점 90(2025-01-08) →
    # 저점 이후 처음으로 120 이상을 회복한 날은 121(2025-01-12).
    # recovery_days = (2025-01-12 − 2025-01-08).days = 4
    assert m["recovery_days"] > 0
    assert m["recovery_days"] == 4


def test_risk_metrics_empty_and_all_loss():
    import pandas as pd
    from simcore.metrics import risk_metrics
    eq = pd.Series([100.0, 90.0], index=pd.date_range("2025-01-01", periods=2))
    m = risk_metrics(eq, pd.DataFrame({"side":["SELL"], "realized_pnl":[-5.0]}))
    assert m["profit_factor"] == 0.0 and m["avg_win"] == 0.0     # 이익 없음
    m2 = risk_metrics(eq, None)                                   # 거래정보 없음
    assert m2["profit_factor"] == 0.0 and m2["expectancy"] == 0.0


def test_benchmark_return_and_none():
    import pandas as pd
    from simcore.metrics import benchmark_return
    idx = pd.date_range("2025-01-01", periods=10)
    s = pd.Series(range(100, 110), index=idx, dtype=float)
    r = benchmark_return(s, idx[0], idx[-1])
    assert r == pytest.approx(109 / 100 - 1)
    assert benchmark_return(None, idx[0], idx[-1]) is None


def test_benchmark_return_empty_series_is_none():
    import pandas as pd
    from simcore.metrics import benchmark_return
    idx = pd.date_range("2025-01-01", periods=10)
    empty = pd.Series([], dtype=float)
    assert benchmark_return(empty, idx[0], idx[-1]) is None


def test_benchmark_return_aligns_nontrading_day_via_asof():
    import pandas as pd
    from simcore.metrics import benchmark_return
    from datetime import date
    idx = pd.bdate_range("2025-01-02", periods=10)  # 2025-01-02(목), 01-03(금), 01-06(월)...
    s = pd.Series(range(100, 110), index=idx, dtype=float)
    # start=비거래일(토요일 2025-01-04) → asof 로 직전 거래일(01-03, 값 101)에 정렬돼야 함
    r = benchmark_return(s, date(2025, 1, 4), idx[-1])
    assert r == pytest.approx(109 / 101 - 1)
